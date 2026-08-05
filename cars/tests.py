from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from django.contrib.auth import get_user_model

from django.contrib import admin

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.services import RoleGroup, ensure_default_role_groups

from cars.models import Car, CarPhoto, CarSpinFrame, VehicleArchiveEvent, VehicleHold

from cars.services import (
    archive_vehicle,
    generate_tracking_code,
    mark_vehicle_as_sold,
    place_vehicle_on_hold,
    publish_vehicle_for_sale,
    release_vehicle_hold,
    restore_archived_vehicle,
)
from cars.spin import assess_car_spin_frames, get_public_spin_payload

from integrations.models import TelegramCustomerActivationToken

from tracking.models import (
    CarStageProgress,
    Stage,
    StageTransition,
    TrackingEvent,
)


class VehicleHoldServiceTests(TestCase):
    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()

        # Normal Employee: inventory permissions, including publish_vehicle.
        self.employee = user_model.objects.create_user(
            username="inventory-employee",
            password="test-password",
            is_staff=True,
        )
        self.employee.groups.add(
            role_groups[RoleGroup.EMPLOYEE],
        )

        # Explicitly authorized Employee for sales operations.
        self.sales_employee = user_model.objects.create_user(
            username="sales-employee",
            password="test-password",
            is_staff=True,
        )
        self.sales_employee.groups.add(
            role_groups[RoleGroup.EMPLOYEE],
        )

        sales_permissions = Permission.objects.filter(
            content_type__app_label="cars",
            codename__in=[
                "hold_vehicle",
                "release_vehicle_hold",
                "sell_vehicle",
            ],
        )
        self.assertEqual(sales_permissions.count(), 3)

        self.sales_employee.user_permissions.add(
            *sales_permissions,
        )

        self.car = Car.objects.create(
            title="Toyota Land Cruiser",
            brand="Toyota",
            model="Land Cruiser",
            status=Car.Status.FOR_SALE,
        )

    def test_generated_tracking_code_is_unique_and_has_prefix(self):
        tracking_code = generate_tracking_code()

        self.assertTrue(tracking_code.startswith("OAL-"))
        self.assertLessEqual(len(tracking_code), 40)
        self.assertFalse(
            Car.objects.filter(
                tracking_code=tracking_code,
            ).exists()
        )

    def test_publish_draft_vehicle_for_sale(self):
        self.car.status = Car.Status.DRAFT
        self.car.save(update_fields=["status"])

        published_car = publish_vehicle_for_sale(
            car_id=self.car.id,
            actor=self.employee,
        )

        self.assertEqual(
            published_car.status,
            Car.Status.FOR_SALE,
        )

    def test_place_vehicle_on_hold_creates_hold_and_changes_status(self):
        hold = place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.sales_employee,
            customer_name="Test Customer",
            customer_phone="09120000000",
        )

        self.car.refresh_from_db()

        self.assertTrue(hold.is_active)
        self.assertEqual(hold.car, self.car)
        self.assertEqual(hold.created_by, self.sales_employee)
        self.assertEqual(self.car.status, Car.Status.ON_HOLD)

    def test_release_vehicle_hold_returns_car_to_for_sale(self):
        hold = place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.sales_employee,
        )

        released_hold = release_vehicle_hold(
            hold_id=hold.id,
            actor=self.sales_employee,
            release_note="Customer decided not to buy.",
        )

        self.car.refresh_from_db()

        self.assertFalse(released_hold.is_active)
        self.assertEqual(
            released_hold.released_by,
            self.sales_employee,
        )
        self.assertIsNotNone(released_hold.released_at)
        self.assertEqual(
            released_hold.release_note,
            "Customer decided not to buy.",
        )
        self.assertEqual(self.car.status, Car.Status.FOR_SALE)

    def test_only_for_sale_vehicle_can_be_placed_on_hold(self):
        self.car.status = Car.Status.SOLD
        self.car.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            place_vehicle_on_hold(
                car_id=self.car.id,
                actor=self.sales_employee,
            )

        self.assertEqual(VehicleHold.objects.count(), 0)

    def test_mark_vehicle_as_sold_assigns_customer_and_tracking_code(self):
        sale_confirmed_stage = Stage.objects.create(
            name="Sale Confirmed",
            order=1,
        )
        preparation_stage = Stage.objects.create(
            name="Vehicle Preparation",
            order=2,
        )

        StageTransition.objects.create(
            from_stage=sale_confirmed_stage,
            to_stage=preparation_stage,
            estimated_duration_days=3,
        )

        hold = place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.sales_employee,
            customer_name="Test Customer",
            customer_phone="09120000000",
        )

        sold_car = mark_vehicle_as_sold(
            car_id=self.car.id,
            actor=self.sales_employee,
            full_name="Test Customer",
            phone="09120000000",
            telegram_id="123456789",
        )

        hold.refresh_from_db()

        self.assertEqual(sold_car.status, Car.Status.SOLD)
        self.assertIsNotNone(sold_car.customer)
        self.assertEqual(sold_car.customer.full_name, "Test Customer")
        self.assertEqual(sold_car.customer.phone, "09120000000")
        self.assertEqual(sold_car.customer.telegram_id, "123456789")
        self.assertTrue(sold_car.tracking_code.startswith("OAL-"))
        self.assertTrue(
            sold_car.telegram_customer_activation_code.startswith("TGC-")
        )
        activation_token = TelegramCustomerActivationToken.objects.get(car=sold_car)
        self.assertNotEqual(
            activation_token.code_hash,
            sold_car.telegram_customer_activation_code,
        )

        self.assertFalse(hold.is_active)
        self.assertEqual(
            hold.release_note,
            "تبدیل رزرو موقت به فروش.",
        )

        self.assertEqual(
            sold_car.current_stage,
            sale_confirmed_stage,
        )
        self.assertEqual(
            CarStageProgress.objects.filter(
                car=sold_car,
            ).count(),
            2,
        )
        self.assertTrue(
            TrackingEvent.objects.filter(
                car=sold_car,
                event_type=TrackingEvent.EventType.TRACKING_STARTED,
            ).exists()
        )

    def test_employee_cannot_place_vehicle_on_hold_without_sales_permission(self):
        with self.assertRaises(ValidationError):
            place_vehicle_on_hold(
                car_id=self.car.id,
                actor=self.employee,
            )

        self.car.refresh_from_db()

        self.assertEqual(self.car.status, Car.Status.FOR_SALE)
        self.assertEqual(VehicleHold.objects.count(), 0)

    def test_employee_cannot_release_hold_without_sales_permission(self):
        hold = place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.sales_employee,
        )

        with self.assertRaises(ValidationError):
            release_vehicle_hold(
                hold_id=hold.id,
                actor=self.employee,
            )

        hold.refresh_from_db()
        self.car.refresh_from_db()

        self.assertTrue(hold.is_active)
        self.assertEqual(self.car.status, Car.Status.ON_HOLD)

    def test_employee_cannot_mark_vehicle_as_sold_without_sales_permission(self):
        sale_confirmed_stage = Stage.objects.create(
            name="Sale Confirmed",
            order=1,
        )
        preparation_stage = Stage.objects.create(
            name="Vehicle Preparation",
            order=2,
        )

        StageTransition.objects.create(
            from_stage=sale_confirmed_stage,
            to_stage=preparation_stage,
            estimated_duration_days=3,
        )

        hold = place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.sales_employee,
        )

        with self.assertRaises(ValidationError):
            mark_vehicle_as_sold(
                car_id=self.car.id,
                actor=self.employee,
                full_name="Test Customer",
                phone="09120000000",
                telegram_id="123456789",
            )

        self.car.refresh_from_db()
        hold.refresh_from_db()

        self.assertEqual(self.car.status, Car.Status.ON_HOLD)
        self.assertIsNone(self.car.tracking_code)
        self.assertTrue(hold.is_active)

    def test_unprivileged_internal_user_cannot_publish_vehicle(self):
        user_model = get_user_model()

        unprivileged_staff = user_model.objects.create_user(
            username="unprivileged-staff",
            password="test-password",
            is_staff=True,
        )

        self.car.status = Car.Status.DRAFT
        self.car.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            publish_vehicle_for_sale(
                car_id=self.car.id,
                actor=unprivileged_staff,
            )

        self.car.refresh_from_db()

        self.assertEqual(self.car.status, Car.Status.DRAFT)

    def test_superuser_can_mark_vehicle_as_sold(self):
        sale_confirmed_stage = Stage.objects.create(
            name="Sale Confirmed",
            order=1,
        )
        preparation_stage = Stage.objects.create(
            name="Vehicle Preparation",
            order=2,
        )

        StageTransition.objects.create(
            from_stage=sale_confirmed_stage,
            to_stage=preparation_stage,
            estimated_duration_days=3,
        )

        place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.sales_employee,
        )

        user_model = get_user_model()

        administrator = user_model.objects.create_superuser(
            username="system-administrator",
            password="test-password",
        )

        sold_car = mark_vehicle_as_sold(
            car_id=self.car.id,
            actor=administrator,
            full_name="Test Customer",
            phone="09120000000",
            telegram_id="123456789",
        )

        self.assertEqual(sold_car.status, Car.Status.SOLD)
        self.assertTrue(sold_car.tracking_code)


class VehicleArchiveServiceTests(TestCase):
    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="archive-employee",
            password="test-password",
            is_staff=True,
        )
        self.employee.groups.add(
            role_groups[RoleGroup.EMPLOYEE],
        )

        self.unprivileged_staff = user_model.objects.create_user(
            username="unprivileged-archive-staff",
            password="test-password",
            is_staff=True,
        )

        self.sales_employee = user_model.objects.create_user(
            username="archive-sales-employee",
            password="test-password",
            is_staff=True,
        )
        self.sales_employee.groups.add(
            role_groups[RoleGroup.EMPLOYEE],
        )

        hold_permission = Permission.objects.get(
            content_type__app_label="cars",
            codename="hold_vehicle",
        )
        self.sales_employee.user_permissions.add(
            hold_permission,
        )

        self.administrator = user_model.objects.create_superuser(
            username="archive-administrator",
            password="test-password",
        )

        self.car = Car.objects.create(
            title="Archive Test Vehicle",
            brand="Toyota",
            model="Camry",
            status=Car.Status.FOR_SALE,
        )

    def test_authorized_employee_can_archive_for_sale_vehicle(self):
        archived_car = archive_vehicle(
            car_id=self.car.id,
            actor=self.employee,
            reason="Vehicle is no longer available in the market.",
            source=VehicleArchiveEvent.Source.ADMIN_DASHBOARD,
        )

        self.assertTrue(archived_car.is_deleted)
        self.assertEqual(
            archived_car.status,
            Car.Status.FOR_SALE,
        )

        event = VehicleArchiveEvent.objects.get(
            car=self.car,
        )

        self.assertEqual(
            event.action,
            VehicleArchiveEvent.Action.ARCHIVED,
        )
        self.assertEqual(
            event.performed_by,
            self.employee,
        )
        self.assertEqual(
            event.previous_status,
            Car.Status.FOR_SALE,
        )
        self.assertEqual(
            event.new_status,
            Car.Status.FOR_SALE,
        )
        self.assertEqual(
            event.source,
            VehicleArchiveEvent.Source.ADMIN_DASHBOARD,
        )

    def test_authorized_employee_can_archive_draft_vehicle(self):
        self.car.status = Car.Status.DRAFT
        self.car.save(update_fields=["status"])

        archived_car = archive_vehicle(
            car_id=self.car.id,
            actor=self.employee,
            reason="Draft vehicle is no longer needed.",
        )

        self.assertTrue(archived_car.is_deleted)
        self.assertEqual(
            archived_car.status,
            Car.Status.DRAFT,
        )

    def test_employee_without_archive_permission_cannot_archive(self):
        with self.assertRaises(ValidationError):
            archive_vehicle(
                car_id=self.car.id,
                actor=self.unprivileged_staff,
                reason="Unauthorized archive attempt.",
            )

        self.car.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(
            VehicleArchiveEvent.objects.count(),
            0,
        )

    def test_held_vehicle_cannot_be_archived(self):
        hold = place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.sales_employee,
        )

        with self.assertRaises(ValidationError):
            archive_vehicle(
                car_id=self.car.id,
                actor=self.employee,
                reason="Attempt to archive a held vehicle.",
            )

        self.car.refresh_from_db()
        hold.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(
            self.car.status,
            Car.Status.ON_HOLD,
        )
        self.assertTrue(hold.is_active)

    def test_sold_vehicle_cannot_be_archived(self):
        self.car.status = Car.Status.SOLD
        self.car.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            archive_vehicle(
                car_id=self.car.id,
                actor=self.employee,
                reason="Attempt to archive a sold vehicle.",
            )

        self.car.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(
            self.car.status,
            Car.Status.SOLD,
        )

    def test_archived_vehicle_cannot_be_placed_on_hold(self):
        archive_vehicle(
            car_id=self.car.id,
            actor=self.employee,
            reason="Vehicle is temporarily removed from inventory.",
        )

        with self.assertRaises(ValidationError):
            place_vehicle_on_hold(
                car_id=self.car.id,
                actor=self.sales_employee,
            )

        self.car.refresh_from_db()

        self.assertTrue(self.car.is_deleted)
        self.assertEqual(
            self.car.status,
            Car.Status.FOR_SALE,
        )
        self.assertEqual(
            VehicleHold.objects.count(),
            0,
        )

    def test_only_system_administrator_can_restore_and_restoration_sets_draft(self):
        archive_vehicle(
            car_id=self.car.id,
            actor=self.employee,
            reason="Vehicle is temporarily unavailable.",
        )

        with self.assertRaises(ValidationError):
            restore_archived_vehicle(
                car_id=self.car.id,
                actor=self.employee,
                reason="Employee attempted restoration.",
            )

        restored_car = restore_archived_vehicle(
            car_id=self.car.id,
            actor=self.administrator,
            reason="Vehicle is available for review again.",
            source=VehicleArchiveEvent.Source.ADMIN_DASHBOARD,
        )

        self.assertFalse(restored_car.is_deleted)
        self.assertEqual(
            restored_car.status,
            Car.Status.DRAFT,
        )

        events = list(
            VehicleArchiveEvent.objects.filter(
                car=self.car,
            ).order_by("pk")
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            events[0].action,
            VehicleArchiveEvent.Action.ARCHIVED,
        )
        self.assertEqual(
            events[1].action,
            VehicleArchiveEvent.Action.RESTORED,
        )
        self.assertEqual(
            events[1].previous_status,
            Car.Status.FOR_SALE,
        )
        self.assertEqual(
            events[1].new_status,
            Car.Status.DRAFT,
        )
        self.assertEqual(
            events[1].performed_by,
            self.administrator,
        )

    def test_non_archived_vehicle_cannot_be_restored(self):
        with self.assertRaises(ValidationError):
            restore_archived_vehicle(
                car_id=self.car.id,
                actor=self.administrator,
                reason="Attempt to restore an active vehicle.",
            )

        self.car.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(
            self.car.status,
            Car.Status.FOR_SALE,
        )

    def test_archive_events_are_immutable(self):
        archive_vehicle(
            car_id=self.car.id,
            actor=self.employee,
            reason="Vehicle archived for audit test.",
        )

        event = VehicleArchiveEvent.objects.get(
            car=self.car,
        )

        event.reason = "Changed reason."

        with self.assertRaises(ValidationError):
            event.save()

        with self.assertRaises(ValidationError):
            event.delete()

    def test_archive_requires_a_non_empty_reason(self):
        with self.assertRaises(ValidationError):
            archive_vehicle(
                car_id=self.car.id,
                actor=self.employee,
                reason="   ",
            )

        self.car.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(VehicleArchiveEvent.objects.count(), 0)

    def test_archive_rejects_an_invalid_source(self):
        with self.assertRaises(ValidationError):
            archive_vehicle(
                car_id=self.car.id,
                actor=self.employee,
                reason="Invalid source test.",
                source="unknown-source",
            )

        self.car.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(VehicleArchiveEvent.objects.count(), 0)

    def test_inactive_employee_cannot_archive_a_vehicle(self):
        self.employee.is_active = False
        self.employee.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            archive_vehicle(
                car_id=self.car.id,
                actor=self.employee,
                reason="Inactive employee archive attempt.",
            )

        self.car.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(VehicleArchiveEvent.objects.count(), 0)


class CarAdminSafetyTests(TestCase):
    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()

        self.inventory_employee = user_model.objects.create_user(
            username="admin-inventory-employee",
            password="test-password",
            is_staff=True,
        )
        self.inventory_employee.groups.add(
            role_groups[RoleGroup.EMPLOYEE],
        )

        self.sales_employee = user_model.objects.create_user(
            username="admin-sales-employee",
            password="test-password",
            is_staff=True,
        )
        self.sales_employee.groups.add(
            role_groups[RoleGroup.EMPLOYEE],
        )

        hold_permission = Permission.objects.get(
            content_type__app_label="cars",
            codename="hold_vehicle",
        )
        release_permission = Permission.objects.get(
            content_type__app_label="cars",
            codename="release_vehicle_hold",
        )

        self.sales_employee.user_permissions.add(
            hold_permission,
            release_permission,
        )

        self.car_admin = admin.site._registry[Car]
        self.hold_admin = admin.site._registry[VehicleHold]
        self.request_factory = RequestFactory()

    def make_request(self, user):
        request = self.request_factory.get("/admin/")
        request.user = user
        return request

    def test_sensitive_car_lifecycle_fields_are_read_only(self):
        protected_fields = {
            "status",
            "tracking_code",
            "customer",
            "current_stage",
            "target_delivery",
            "channel_message_ids",
            "is_deleted",
        }

        self.assertTrue(protected_fields.issubset(set(self.car_admin.readonly_fields)))

    def test_admin_actions_follow_vehicle_permissions(self):
        inventory_request = self.make_request(self.inventory_employee)
        sales_request = self.make_request(self.sales_employee)

        inventory_car_actions = self.car_admin.get_actions(inventory_request)
        sales_car_actions = self.car_admin.get_actions(sales_request)

        self.assertIn(
            "publish_selected_cars",
            inventory_car_actions,
        )
        self.assertNotIn(
            "place_selected_vehicle_on_hold",
            inventory_car_actions,
        )
        self.assertIn(
            "place_selected_vehicle_on_hold",
            sales_car_actions,
        )

        inventory_hold_actions = self.hold_admin.get_actions(inventory_request)
        sales_hold_actions = self.hold_admin.get_actions(sales_request)

        self.assertNotIn(
            "release_selected_holds",
            inventory_hold_actions,
        )
        self.assertIn(
            "release_selected_holds",
            sales_hold_actions,
        )


class VehicleArchiveAdminWorkflowTests(TestCase):
    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="admin-archive-employee",
            password="test-password",
            is_staff=True,
        )
        self.employee.groups.add(
            role_groups[RoleGroup.EMPLOYEE],
        )

        self.unprivileged_staff = user_model.objects.create_user(
            username="admin-unprivileged-archive-staff",
            password="test-password",
            is_staff=True,
        )

        self.administrator = user_model.objects.create_superuser(
            username="admin-archive-administrator",
            password="test-password",
        )

        self.car = Car.objects.create(
            title="Admin Archive Test Vehicle",
            brand="Toyota",
            model="Corolla",
            status=Car.Status.FOR_SALE,
        )

        self.car_admin = admin.site._registry[Car]
        self.archive_event_admin = admin.site._registry[VehicleArchiveEvent]
        self.request_factory = RequestFactory()

    def make_request(self, user):
        request = self.request_factory.get("/admin/")
        request.user = user
        return request

    def test_car_admin_disables_hard_delete_even_for_system_administrator(self):
        request = self.make_request(self.administrator)

        self.assertFalse(
            self.car_admin.has_delete_permission(
                request,
                self.car,
            )
        )
        self.assertNotIn(
            "delete_selected",
            self.car_admin.get_actions(request),
        )

    def test_authorized_employee_can_open_the_archive_form(self):
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse(
                "admin:cars_car_archive",
                args=[self.car.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "دلیل عملیات")
        self.assertContains(response, 'name="reason"')

    def test_archive_form_requires_a_non_empty_reason(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "admin:cars_car_archive",
                args=[self.car.id],
            ),
            {"reason": "   "},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "ثبت دلیل برای این عملیات الزامی است.",
        )

        self.car.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(VehicleArchiveEvent.objects.count(), 0)

    def test_archive_form_uses_shared_service_and_creates_audit_event(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "admin:cars_car_archive",
                args=[self.car.id],
            ),
            {"reason": "Vehicle removed from active inventory."},
        )

        self.assertRedirects(
            response,
            reverse(
                "admin:cars_car_change",
                args=[self.car.id],
            ),
        )

        self.car.refresh_from_db()
        event = VehicleArchiveEvent.objects.get(car=self.car)

        self.assertTrue(self.car.is_deleted)
        self.assertEqual(event.performed_by, self.employee)
        self.assertEqual(
            event.source,
            VehicleArchiveEvent.Source.ADMIN_DASHBOARD,
        )
        self.assertEqual(
            event.reason,
            "Vehicle removed from active inventory.",
        )

    def test_unprivileged_staff_cannot_open_the_archive_form(self):
        self.client.force_login(self.unprivileged_staff)

        response = self.client.get(
            reverse(
                "admin:cars_car_archive",
                args=[self.car.id],
            )
        )

        self.assertEqual(response.status_code, 403)

        self.car.refresh_from_db()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(VehicleArchiveEvent.objects.count(), 0)

    def test_employee_cannot_open_the_restore_form(self):
        archive_vehicle(
            car_id=self.car.id,
            actor=self.employee,
            reason="Prepare restore authorization test.",
        )

        self.client.force_login(self.employee)

        response = self.client.get(
            reverse(
                "admin:cars_car_restore",
                args=[self.car.id],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_system_administrator_can_restore_from_admin_as_draft(self):
        archive_vehicle(
            car_id=self.car.id,
            actor=self.employee,
            reason="Prepare restore workflow test.",
        )

        self.client.force_login(self.administrator)

        response = self.client.post(
            reverse(
                "admin:cars_car_restore",
                args=[self.car.id],
            ),
            {"reason": "Vehicle approved for a new review."},
        )

        self.assertRedirects(
            response,
            reverse(
                "admin:cars_car_change",
                args=[self.car.id],
            ),
        )

        self.car.refresh_from_db()
        restore_event = VehicleArchiveEvent.objects.filter(
            car=self.car,
            action=VehicleArchiveEvent.Action.RESTORED,
        ).get()

        self.assertFalse(self.car.is_deleted)
        self.assertEqual(self.car.status, Car.Status.DRAFT)
        self.assertEqual(
            restore_event.performed_by,
            self.administrator,
        )
        self.assertEqual(
            restore_event.source,
            VehicleArchiveEvent.Source.ADMIN_DASHBOARD,
        )

    def test_archive_event_admin_is_read_only_and_superuser_only(self):
        archive_vehicle(
            car_id=self.car.id,
            actor=self.employee,
            reason="Prepare archive event admin test.",
        )

        administrator_request = self.make_request(self.administrator)
        employee_request = self.make_request(self.employee)

        self.assertTrue(
            self.archive_event_admin.has_view_permission(
                administrator_request,
            )
        )
        self.assertFalse(
            self.archive_event_admin.has_view_permission(
                employee_request,
            )
        )
        self.assertFalse(
            self.archive_event_admin.has_add_permission(
                administrator_request,
            )
        )
        self.assertFalse(
            self.archive_event_admin.has_change_permission(
                administrator_request,
            )
        )
        self.assertFalse(
            self.archive_event_admin.has_delete_permission(
                administrator_request,
            )
        )


class CarSpinFrameReadinessTests(TestCase):
    def setUp(self):
        self.temporary_media = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.temporary_media.name)
        self.media_override.enable()
        self.car = Car.objects.create(
            title="360 Test Vehicle",
            brand="Test Brand",
            model="Spin Model",
            status=Car.Status.FOR_SALE,
        )

    def tearDown(self):
        self.media_override.disable()
        self.temporary_media.cleanup()

    @staticmethod
    def make_frame_file(sequence, size=(384, 256)):
        image = Image.new("RGB", size, color=(12, 69, 145))
        output = BytesIO()
        image.save(output, format="WEBP", quality=80)
        return SimpleUploadedFile(
            f"frame-{sequence:02d}.webp",
            output.getvalue(),
            content_type="image/webp",
        )

    def create_frames(self, sequences, size=(384, 256)):
        for sequence in sequences:
            CarSpinFrame.objects.create(
                car=self.car,
                sequence=sequence,
                image=self.make_frame_file(sequence, size=size),
            )

    def test_twelve_contiguous_compatible_frames_are_technically_ready(self):
        self.create_frames(range(1, 13))

        readiness = assess_car_spin_frames(self.car)

        self.assertTrue(readiness.is_ready)
        self.assertEqual(readiness.frame_count, 12)
        self.assertFalse(readiness.is_recommended)
        self.assertEqual(readiness.messages, ())

    def test_gaps_and_aspect_ratio_mismatch_are_not_ready(self):
        self.create_frames(range(1, 12))
        CarSpinFrame.objects.create(
            car=self.car,
            sequence=13,
            image=self.make_frame_file(13, size=(384, 300)),
        )

        readiness = assess_car_spin_frames(self.car)

        self.assertFalse(readiness.is_ready)
        self.assertTrue(
            any("شمارهٔ فریم‌ها" in message for message in readiness.messages)
        )
        self.assertTrue(
            any("نسبت تصویر" in message for message in readiness.messages)
        )

    def test_public_payload_requires_explicit_enablement_and_stays_safe(self):
        self.create_frames(range(1, 13))

        self.assertIsNone(get_public_spin_payload(self.car))

        self.car.spin_360_enabled = True
        self.car.save(update_fields=["spin_360_enabled"])
        payload = get_public_spin_payload(self.car)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["frame_count"], 12)
        self.assertEqual(len(payload["frame_urls"]), 12)

        self.car.spin_frames.get(sequence=12).delete()
        self.assertIsNone(get_public_spin_payload(self.car))


class PublicVehicleGalleryTemplateTests(TestCase):
    """The public gallery must work from normal ``CarPhoto`` records for every car."""

    def setUp(self):
        self.temporary_media = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.temporary_media.name)
        self.media_override.enable()

        self.car = Car.objects.create(
            title="Gallery Test Vehicle",
            brand="Test Brand",
            model="Gallery Model",
            status=Car.Status.FOR_SALE,
        )
        self.cover_photo = CarPhoto.objects.create(
            car=self.car,
            image=SimpleUploadedFile(
                "cover.jpg",
                b"cover-image",
                content_type="image/jpeg",
            ),
            alt_text="Cover image",
            is_cover=True,
        )
        self.alternate_photo = CarPhoto.objects.create(
            car=self.car,
            image=SimpleUploadedFile(
                "alternate.jpg",
                b"alternate-image",
                content_type="image/jpeg",
            ),
            alt_text="Alternate image",
            sort_order=1,
        )

    def tearDown(self):
        self.media_override.disable()
        self.temporary_media.cleanup()

    def test_public_detail_renders_an_interactive_control_for_every_photo(self):
        response = self.client.get(self.car.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-vehicle-gallery")
        self.assertContains(response, "data-gallery-main-image")
        self.assertContains(response, "data-gallery-thumbnail", count=2)
        self.assertContains(response, "public-site.js?v=")
        self.assertContains(
            response,
            f'data-gallery-image-src="{self.alternate_photo.image.url}"',
        )
        self.assertContains(response, 'aria-pressed="true"')

    @patch("cars.views.get_public_spin_payload")
    def test_spin_and_photo_modes_are_both_available_when_a_car_has_360_view(
        self,
        get_public_spin_payload_mock,
    ):
        get_public_spin_payload_mock.return_value = {
            "frame_urls": ["/media/cars/spins/frame-01.webp"],
            "frame_count": 1,
        }

        response = self.client.get(self.car.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-gallery-spin-viewer")
        self.assertContains(response, "data-gallery-spin-control")
        self.assertContains(response, "data-gallery-main-image")
        self.assertContains(response, "data-gallery-thumbnail", count=2)
