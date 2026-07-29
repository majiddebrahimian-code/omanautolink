from io import StringIO

from django.core.management import call_command

from django.contrib.auth.models import Group
from django.test import TestCase

from accounts.services import RoleGroup, ensure_default_role_groups

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.models import StaffProfile
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
