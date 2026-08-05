from io import StringIO

from django.core.management import call_command

from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from accounts.services import (
    RoleGroup,
    StaffBusinessRole,
    create_staff_member,
    ensure_default_role_groups,
    reset_staff_password,
    set_staff_active_state,
    update_staff_member,
)

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import StaffManagementEvent, StaffProfile
from cars.models import Car
from tracking.models import Stage, StageTransition
from tracking.services import confirm_stage, start_tracking_for_sold_car


class DefaultRoleGroupTests(TestCase):
    def test_role_setup_creates_groups_with_core_permissions(self):
        ensure_default_role_groups()

        employee_group = Group.objects.get(
            name=RoleGroup.EMPLOYEE,
        )
        clearance_group = Group.objects.get(
            name=RoleGroup.CLEARANCE_EMPLOYEE,
        )

        self.assertTrue(
            employee_group.permissions.filter(
                content_type__app_label="cars",
                codename="change_car",
            ).exists()
        )
        self.assertTrue(
            employee_group.permissions.filter(
                content_type__app_label="cars",
                codename="publish_vehicle",
            ).exists()
        )

        self.assertTrue(
            clearance_group.permissions.filter(
                content_type__app_label="tracking",
                codename="confirm_tracking_stage",
            ).exists()
        )

        # An ordinary Employee cannot confirm tracking stages.
        self.assertFalse(
            employee_group.permissions.filter(
                content_type__app_label="tracking",
                codename="confirm_tracking_stage",
            ).exists()
        )

        # Clearance staff cannot sell vehicles by default.
        self.assertFalse(
            clearance_group.permissions.filter(
                content_type__app_label="cars",
                codename="sell_vehicle",
            ).exists()
        )

    def test_role_setup_is_idempotent(self):
        ensure_default_role_groups()
        ensure_default_role_groups()

        self.assertEqual(
            Group.objects.filter(
                name=RoleGroup.EMPLOYEE,
            ).count(),
            1,
        )
        self.assertEqual(
            Group.objects.filter(
                name=RoleGroup.CLEARANCE_EMPLOYEE,
            ).count(),
            1,
        )


class ClearanceRoleStageAuthorizationTests(TestCase):
    def setUp(self):
        ensure_default_role_groups()

        self.sale_confirmed_stage = Stage.objects.create(
            name="Sale Confirmed",
            order=1,
        )
        self.clearance_stage = Stage.objects.create(
            name="Customs Clearance",
            order=2,
        )

        StageTransition.objects.create(
            from_stage=self.sale_confirmed_stage,
            to_stage=self.clearance_stage,
            estimated_duration_days=5,
        )

        user_model = get_user_model()

        self.tracking_creator = user_model.objects.create_user(
            username="tracking-creator",
            password="test-password",
        )

    def create_sold_car(self, tracking_code):
        car = Car.objects.create(
            title="Toyota Land Cruiser",
            brand="Toyota",
            model="Land Cruiser",
            status=Car.Status.SOLD,
            tracking_code=tracking_code,
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.tracking_creator,
        )

        return car

    def create_user_with_role(
        self,
        *,
        username,
        group_name,
        assign_stage=True,
        is_staff=True,
        is_active=True,
    ):
        user_model = get_user_model()

        user = user_model.objects.create_user(
            username=username,
            password="test-password",
            is_staff=is_staff,
            is_active=is_active,
        )

        group = Group.objects.get(name=group_name)
        user.groups.add(group)

        profile = StaffProfile.objects.create(user=user)

        if assign_stage:
            profile.assigned_stages.add(self.clearance_stage)

        return user

    def test_assigned_clearance_employee_can_confirm_stage(self):
        car = self.create_sold_car(
            "OAL-clearance-role-allowed",
        )

        clearance_employee = self.create_user_with_role(
            username="clearance-employee",
            group_name=RoleGroup.CLEARANCE_EMPLOYEE,
        )

        progress = confirm_stage(
            car=car,
            stage=self.clearance_stage,
            staff=clearance_employee,
        )

        self.assertEqual(
            progress.confirmed_by,
            clearance_employee,
        )

    def test_general_employee_cannot_confirm_even_if_stage_is_assigned(self):
        car = self.create_sold_car(
            "OAL-general-employee-blocked",
        )

        employee = self.create_user_with_role(
            username="general-employee",
            group_name=RoleGroup.EMPLOYEE,
        )

        with self.assertRaises(ValidationError):
            confirm_stage(
                car=car,
                stage=self.clearance_stage,
                staff=employee,
            )

    def test_clearance_employee_without_stage_assignment_cannot_confirm(self):
        car = self.create_sold_car(
            "OAL-clearance-no-stage",
        )

        clearance_employee = self.create_user_with_role(
            username="clearance-without-stage",
            group_name=RoleGroup.CLEARANCE_EMPLOYEE,
            assign_stage=False,
        )

        with self.assertRaises(ValidationError):
            confirm_stage(
                car=car,
                stage=self.clearance_stage,
                staff=clearance_employee,
            )

    def test_inactive_clearance_employee_cannot_confirm(self):
        car = self.create_sold_car(
            "OAL-inactive-clearance",
        )

        inactive_employee = self.create_user_with_role(
            username="inactive-clearance",
            group_name=RoleGroup.CLEARANCE_EMPLOYEE,
            is_active=False,
        )

        with self.assertRaises(ValidationError):
            confirm_stage(
                car=car,
                stage=self.clearance_stage,
                staff=inactive_employee,
            )

    def test_non_staff_clearance_employee_cannot_confirm(self):
        car = self.create_sold_car(
            "OAL-non-staff-clearance",
        )

        non_staff_employee = self.create_user_with_role(
            username="non-staff-clearance",
            group_name=RoleGroup.CLEARANCE_EMPLOYEE,
            is_staff=False,
        )

        with self.assertRaises(ValidationError):
            confirm_stage(
                car=car,
                stage=self.clearance_stage,
                staff=non_staff_employee,
            )

    def test_superuser_can_confirm_without_profile_or_stage_assignment(self):
        car = self.create_sold_car(
            "OAL-superuser-confirmation",
        )

        user_model = get_user_model()

        administrator = user_model.objects.create_superuser(
            username="system-administrator",
            password="test-password",
        )

        progress = confirm_stage(
            car=car,
            stage=self.clearance_stage,
            staff=administrator,
        )

        self.assertEqual(
            progress.confirmed_by,
            administrator,
        )


class SyncRolesCommandTests(TestCase):
    def test_sync_roles_command_creates_baseline_groups(self):
        output = StringIO()

        call_command(
            "sync_roles",
            stdout=output,
        )

        self.assertTrue(
            Group.objects.filter(
                name=RoleGroup.EMPLOYEE,
            ).exists()
        )
        self.assertTrue(
            Group.objects.filter(
                name=RoleGroup.CLEARANCE_EMPLOYEE,
            ).exists()
        )
        self.assertIn(
            RoleGroup.EMPLOYEE,
            output.getvalue(),
        )
        self.assertIn(
            RoleGroup.CLEARANCE_EMPLOYEE,
            output.getvalue(),
        )


class StaffAccountLifecycleServiceTests(TestCase):
    def setUp(self):
        ensure_default_role_groups()
        user_model = get_user_model()
        self.administrator = user_model.objects.create_superuser(
            username="staff-system-administrator",
            password="strong-admin-password-123",
        )
        self.first_stage = Stage.objects.create(name="Purchase confirmed", order=1)
        self.clearance_stage = Stage.objects.create(name="Customs", order=2)

    def create_staff(self, **overrides):
        payload = {
            "actor": self.administrator,
            "username": "test-staff-member",
            "raw_password": "A-secure-password-123!",
            "first_name": "Ali",
            "last_name": "Employee",
            "email": "ali@example.com",
            "phone": "09120000000",
            "role": StaffBusinessRole.CLEARANCE_EMPLOYEE,
            "assigned_stages": [self.clearance_stage],
            "exceptional_permissions": [],
        }
        payload.update(overrides)
        return create_staff_member(**payload)

    def test_create_clearance_employee_builds_profile_role_stage_and_audit_event(self):
        staff_user = self.create_staff()
        profile = StaffProfile.objects.get(user=staff_user)

        self.assertTrue(staff_user.is_staff)
        self.assertTrue(staff_user.is_active)
        self.assertTrue(
            staff_user.groups.filter(name=RoleGroup.CLEARANCE_EMPLOYEE).exists()
        )
        self.assertTrue(staff_user.has_perm("tracking.confirm_tracking_stage"))
        self.assertEqual(list(profile.assigned_stages.all()), [self.clearance_stage])

        event = StaffManagementEvent.objects.get(staff_user=staff_user)
        self.assertEqual(event.action, StaffManagementEvent.Action.CREATED)
        self.assertEqual(event.performed_by, self.administrator)
        self.assertEqual(event.changes["after"]["role"], StaffBusinessRole.CLEARANCE_EMPLOYEE)

    def test_general_employee_can_receive_explicit_stage_confirmation_capability(self):
        confirmation_permission = Permission.objects.get(
            content_type__app_label="tracking",
            codename="confirm_tracking_stage",
        )
        staff_user = self.create_staff(
            username="authorized-general-employee",
            email="authorized@example.com",
            role=StaffBusinessRole.EMPLOYEE,
            assigned_stages=[self.clearance_stage],
            exceptional_permissions=[confirmation_permission],
        )

        profile = StaffProfile.objects.get(user=staff_user)
        self.assertTrue(staff_user.has_perm("tracking.confirm_tracking_stage"))
        self.assertEqual(list(profile.assigned_stages.all()), [self.clearance_stage])

    def test_removing_stage_confirmation_capability_clears_stage_assignments(self):
        staff_user = self.create_staff()

        update_staff_member(
            staff_user=staff_user,
            actor=self.administrator,
            username=staff_user.username,
            first_name=staff_user.first_name,
            last_name=staff_user.last_name,
            email=staff_user.email,
            phone="09123333333",
            role=StaffBusinessRole.EMPLOYEE,
            assigned_stages=[self.clearance_stage],
            exceptional_permissions=[],
        )

        staff_user.refresh_from_db()
        profile = StaffProfile.objects.get(user=staff_user)
        self.assertFalse(staff_user.has_perm("tracking.confirm_tracking_stage"))
        self.assertFalse(profile.assigned_stages.exists())
        self.assertEqual(
            StaffManagementEvent.objects.filter(
                staff_user=staff_user,
                action=StaffManagementEvent.Action.UPDATED,
            ).count(),
            1,
        )

    def test_deactivation_removes_stage_responsibility_and_preserves_account_history(self):
        staff_user = self.create_staff()

        deactivated_user = set_staff_active_state(
            staff_user=staff_user,
            actor=self.administrator,
            is_active=False,
            reason="End of employment",
        )

        deactivated_user.refresh_from_db()
        profile = StaffProfile.objects.get(user=deactivated_user)
        self.assertFalse(deactivated_user.is_active)
        self.assertFalse(profile.assigned_stages.exists())
        self.assertTrue(
            StaffManagementEvent.objects.filter(
                staff_user=deactivated_user,
                action=StaffManagementEvent.Action.DEACTIVATED,
            ).exists()
        )

    def test_password_reset_uses_django_password_hashing_and_is_audited(self):
        staff_user = self.create_staff()
        original_password_hash = staff_user.password

        reset_staff_password(
            staff_user=staff_user,
            actor=self.administrator,
            raw_password="Another-secure-password-456!",
        )

        staff_user.refresh_from_db()
        self.assertNotEqual(staff_user.password, original_password_hash)
        self.assertTrue(staff_user.check_password("Another-secure-password-456!"))
        self.assertTrue(
            StaffManagementEvent.objects.filter(
                staff_user=staff_user,
                action=StaffManagementEvent.Action.PASSWORD_RESET,
            ).exists()
        )

    def test_non_administrator_cannot_create_a_staff_account(self):
        user_model = get_user_model()
        ordinary_employee = user_model.objects.create_user(
            username="ordinary-staff-actor",
            password="test-password",
            is_staff=True,
        )

        with self.assertRaises(ValidationError):
            create_staff_member(
                actor=ordinary_employee,
                username="denied-staff",
                raw_password="A-secure-password-123!",
                role=StaffBusinessRole.EMPLOYEE,
            )
