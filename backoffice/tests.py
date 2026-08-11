from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from PIL import Image

from accounts.services import RoleGroup, ensure_default_role_groups
from blog.models import Category, Post
from cars.models import (
    Car,
    CarPhoto,
    VehicleArchiveEvent,
    VehicleHold,
    VehicleInventoryEvent,
)
from cars.services import create_inventory_car
from customers.models import Customer, CustomVehicleRequest, CustomVehicleRequestReadReceipt
from customers.services import create_custom_vehicle_request
from accounts.models import StaffManagementEvent, StaffProfile
from backoffice.navigation import build_panel_navigation
from tracking.models import CarStageProgress, Stage, StageTransition, TrackingEvent
from tracking.services import complete_stage, confirm_stage, start_tracking_for_sold_car
from core.models import HeaderNavigationItem, SiteConfiguration
from integrations.models import (
    TelegramChannel,
    TelegramInboundUpdate,
    TelegramOutboxMessage,
    TelegramStaffLink,
    TelegramVehiclePublication,
)


class BackofficeSidebarNavigationTests(TestCase):
    def setUp(self):
        self.administrator = get_user_model().objects.create_superuser(
            username="sidebar-administrator",
            password="test-password",
        )

    def test_only_the_section_of_the_current_submenu_is_open(self):
        navigation = build_panel_navigation(
            self.administrator,
            current_view_name="backoffice:telegram_settings",
        )

        open_sections = [section for section in navigation if section["is_open"]]
        self.assertEqual(len(open_sections), 1)

        active_items = [
            item
            for section in navigation
            for item in section["items"]
            if item.get("is_active")
        ]
        self.assertEqual(len(active_items), 1)
        self.assertEqual(active_items[0]["url_name"], "backoffice:telegram_settings")

    def test_telegram_settings_use_the_dedicated_rtl_control_layout(self):
        self.client.force_login(self.administrator)

        response = self.client.get(reverse("backoffice:telegram_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "telegram-settings-layout")
        self.assertContains(response, "telegram-toggle-card")
        self.assertContains(response, "علامت‌گذاری پست به‌عنوان فروخته‌شده")
        self.assertContains(response, "حذف پست از کانال")


class BackofficeMachineWorkflowTests(TestCase):
    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="backoffice-inventory-employee",
            password="test-password",
            is_staff=True,
        )
        self.employee.groups.add(role_groups[RoleGroup.EMPLOYEE])

        self.clearance_employee = user_model.objects.create_user(
            username="backoffice-clearance-employee",
            password="test-password",
            is_staff=True,
        )
        self.clearance_employee.groups.add(role_groups[RoleGroup.CLEARANCE_EMPLOYEE])

        self.customer = Customer.objects.create(
            full_name="مشتری آزمون",
            phone="09120000000",
            telegram_id="backoffice-customer",
        )

    @staticmethod
    def inventory_payload(**overrides):
        data = {
            "title": "تویوتا لندکروزر",
            "brand": "Toyota",
            "model": "Land Cruiser",
            "year": "2024",
            "color": "سفید",
            "mileage": "1200",
            "price_amount": "2500000000",
            "description": "توضیحات آزمون",
            "location": "مسقط",
            "seo_title": "خرید لندکروزر",
            "seo_description": "توضیحات SEO آزمون",
            "seo_keywords": "لندکروزر، خودرو عمان",
        }
        data.update(overrides)
        return data

    def create_machine(self, **overrides):
        return Car.objects.create(
            title=overrides.pop("title", "ماشین آزمون"),
            brand=overrides.pop("brand", "Toyota"),
            model=overrides.pop("model", "Camry"),
            **overrides,
        )

    def test_employee_creates_a_draft_and_an_immutable_inventory_event(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:machine_create"),
            data=self.inventory_payload(),
        )

        self.assertRedirects(response, reverse("backoffice:machine_list"))

        machine = Car.objects.get(title="تویوتا لندکروزر")
        event = VehicleInventoryEvent.objects.get(car=machine)

        self.assertEqual(machine.status, Car.Status.DRAFT)
        self.assertFalse(machine.is_deleted)
        self.assertIsNone(machine.customer)
        self.assertIsNone(machine.tracking_code)
        self.assertEqual(event.action, VehicleInventoryEvent.Action.CREATED)
        self.assertEqual(event.performed_by, self.employee)
        self.assertEqual(event.source, VehicleInventoryEvent.Source.BACKOFFICE)
        self.assertEqual(event.changes["fields"]["title"]["after"], machine.title)

    def test_clearance_employee_cannot_open_or_submit_machine_creation(self):
        self.client.force_login(self.clearance_employee)
        create_url = reverse("backoffice:machine_create")

        self.assertEqual(self.client.get(create_url).status_code, 403)
        self.assertEqual(
            self.client.post(create_url, data=self.inventory_payload()).status_code,
            403,
        )
        self.assertEqual(Car.objects.count(), 0)

    def test_create_service_rejects_lifecycle_fields_even_for_authorized_staff(self):
        payload = self.inventory_payload(status=Car.Status.FOR_SALE)

        with self.assertRaises(ValidationError):
            create_inventory_car(
                actor=self.employee,
                vehicle_data=payload,
            )

        self.assertEqual(Car.objects.count(), 0)

    def test_machine_edit_updates_allowed_fields_and_records_a_json_safe_diff(self):
        machine = self.create_machine(
            status=Car.Status.DRAFT,
            price_amount=1000000000,
        )
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:machine_edit", args=[machine.pk]),
            data=self.inventory_payload(
                title="تویوتا لندکروزر جدید",
                price_amount="2600000000",
            ),
        )

        self.assertRedirects(response, reverse("backoffice:machine_list"))
        machine.refresh_from_db()
        event = VehicleInventoryEvent.objects.filter(
            car=machine,
            action=VehicleInventoryEvent.Action.UPDATED,
        ).get()

        self.assertEqual(machine.title, "تویوتا لندکروزر جدید")
        self.assertEqual(event.performed_by, self.employee)
        self.assertEqual(
            event.changes["fields"]["price_amount"]["before"],
            "1000000000",
        )
        self.assertEqual(
            event.changes["fields"]["price_amount"]["after"],
            "2600000000",
        )

    def test_edit_of_a_sold_machine_is_rejected_by_the_shared_service(self):
        machine = self.create_machine(
            status=Car.Status.SOLD,
            customer=self.customer,
            tracking_code="OAL-panel-sold",
        )
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:machine_edit", args=[machine.pk]),
            data=self.inventory_payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "پس از رزرو یا فروش، اطلاعات موجودی ماشین از این صفحه قابل ویرایش نیست.",
        )
        machine.refresh_from_db()
        self.assertEqual(machine.status, Car.Status.SOLD)
        self.assertEqual(VehicleInventoryEvent.objects.count(), 0)

    def test_machine_archive_is_soft_and_creates_the_existing_archive_audit_event(self):
        machine = self.create_machine(status=Car.Status.FOR_SALE)
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:machine_archive", args=[machine.pk]),
            data={"reason": "تصمیم به خروج از موجودی فعال"},
        )

        self.assertRedirects(response, reverse("backoffice:machine_list"))
        machine.refresh_from_db()
        event = VehicleArchiveEvent.objects.get(car=machine)

        self.assertTrue(machine.is_deleted)
        self.assertEqual(event.performed_by, self.employee)
        self.assertEqual(event.source, VehicleArchiveEvent.Source.ADMIN_DASHBOARD)

    def test_machine_list_shows_actions_only_to_an_authorized_inventory_employee(self):
        machine = self.create_machine(status=Car.Status.DRAFT)
        self.client.force_login(self.employee)

        response = self.client.get(reverse("backoffice:machine_list"))

        self.assertContains(response, "افزودن ماشین")
        self.assertContains(
            response,
            reverse("backoffice:machine_edit", args=[machine.pk]),
        )
        self.assertContains(
            response,
            reverse("backoffice:machine_archive", args=[machine.pk]),
        )

        self.client.force_login(self.clearance_employee)
        response = self.client.get(reverse("backoffice:machine_list"))

        self.assertEqual(response.status_code, 403)

    def test_machine_list_shows_and_filters_telegram_publication_state(self):
        published_machine = self.create_machine(
            title="Published machine",
            status=Car.Status.FOR_SALE,
        )
        unpublished_machine = self.create_machine(
            title="Unpublished machine",
            status=Car.Status.DRAFT,
        )
        channel = TelegramChannel.objects.create(
            name="Machine list test channel",
            chat_id=-100777001,
        )
        outbox = TelegramOutboxMessage.objects.create(
            operation=TelegramOutboxMessage.Operation.SEND_MESSAGE,
            chat_id=channel.chat_id,
            body="Published vehicle",
            message_type="test_vehicle_publication",
            idempotency_key="backoffice-machine-list-telegram-state",
            status=TelegramOutboxMessage.Status.SENT,
            telegram_message_id=771,
        )
        TelegramVehiclePublication.objects.create(
            car=published_machine,
            channel=channel,
            latest_outbox_message=outbox,
            telegram_message_id=771,
        )
        self.client.force_login(self.employee)

        response = self.client.get(reverse("backoffice:machine_list"))

        self.assertContains(response, "منتشرشده")
        self.assertContains(response, "منتشر نشده")
        self.assertContains(response, "backoffice-machine-filter-form")

        filtered_response = self.client.get(
            reverse("backoffice:machine_list"),
            {"telegram": "published"},
        )
        self.assertContains(filtered_response, published_machine.title)
        self.assertNotContains(filtered_response, unpublished_machine.title)

    def test_inventory_forms_offer_telegram_publication_to_authorized_employee(self):
        machine = self.create_machine(status=Car.Status.DRAFT)
        self.client.force_login(self.employee)

        create_response = self.client.get(reverse("backoffice:machine_create"))
        edit_response = self.client.get(
            reverse("backoffice:machine_edit", args=[machine.pk])
        )

        self.assertContains(create_response, "انتشار در Telegram")
        self.assertContains(edit_response, "انتشار در Telegram")

    def test_publish_action_moves_a_draft_to_for_sale(self):
        machine = self.create_machine(status=Car.Status.DRAFT)
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:machine_publish", args=[machine.pk]),
        )

        self.assertRedirects(response, reverse("backoffice:machine_list"))
        machine.refresh_from_db()
        self.assertEqual(machine.status, Car.Status.FOR_SALE)

    def test_authorized_sales_employee_can_create_a_temporary_hold(self):
        machine = self.create_machine(status=Car.Status.FOR_SALE)
        hold_permission = Permission.objects.get(
            content_type__app_label="cars",
            codename="hold_vehicle",
        )
        self.employee.user_permissions.add(hold_permission)
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:machine_hold_create", args=[machine.pk]),
            data={
                "customer_name": "مشتری مذاکره",
                "customer_phone": "09121111111",
                "expires_at": "",
            },
        )

        self.assertRedirects(response, reverse("backoffice:vehicle_hold_list"))
        machine.refresh_from_db()
        hold = VehicleHold.objects.get(car=machine)

        self.assertEqual(machine.status, Car.Status.ON_HOLD)
        self.assertTrue(hold.is_active)
        self.assertEqual(hold.created_by, self.employee)

    def test_pending_and_delivered_lists_use_the_shared_car_statuses_and_search(self):
        sold_machine = self.create_machine(
            title="ماشین فروخته‌شده",
            status=Car.Status.SOLD,
            customer=self.customer,
            tracking_code="OAL-pending",
        )
        transit_machine = self.create_machine(
            title="ماشین در مسیر",
            status=Car.Status.IN_TRANSIT,
            customer=self.customer,
            tracking_code="OAL-transit",
        )
        delivered_machine = self.create_machine(
            title="ماشین تحویل‌شده",
            status=Car.Status.DELIVERED,
            customer=self.customer,
            tracking_code="OAL-delivered",
        )
        self.client.force_login(self.employee)

        pending_response = self.client.get(
            reverse("backoffice:pending_delivery_list"),
            {"q": self.customer.full_name},
        )
        delivered_response = self.client.get(
            reverse("backoffice:delivered_machine_list"),
            {"q": "OAL-delivered"},
        )

        self.assertContains(pending_response, sold_machine.title)
        self.assertContains(pending_response, transit_machine.title)
        self.assertNotContains(pending_response, delivered_machine.title)
        self.assertContains(delivered_response, delivered_machine.title)
        self.assertNotContains(delivered_response, sold_machine.title)


class BackofficeDeliveryOperationsTests(TestCase):
    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()

        self.administrator = user_model.objects.create_superuser(
            username="delivery-system-admin",
            password="test-password",
            email="admin@example.com",
        )
        self.clearance_employee = user_model.objects.create_user(
            username="delivery-clearance-worker",
            password="test-password",
            is_staff=True,
        )
        self.clearance_employee.groups.add(
            role_groups[RoleGroup.CLEARANCE_EMPLOYEE]
        )
        self.clearance_profile = StaffProfile.objects.create(
            user=self.clearance_employee,
        )
        self.first_stage = Stage.objects.create(name="ثبت فروش", order=1)
        self.second_stage = Stage.objects.create(name="ارسال از عمان", order=2)
        self.third_stage = Stage.objects.create(name="ترخیص", order=3)
        StageTransition.objects.create(
            from_stage=self.first_stage,
            to_stage=self.second_stage,
            estimated_duration_days=3,
        )
        StageTransition.objects.create(
            from_stage=self.second_stage,
            to_stage=self.third_stage,
            estimated_duration_days=5,
        )
        self.clearance_profile.assigned_stages.add(
            self.second_stage,
            self.third_stage,
        )
        self.customer = Customer.objects.create(
            full_name="خریدار پروندهٔ تحویل",
            phone="09120000001",
            telegram_id="delivery-customer",
        )
        self.machine = Car.objects.create(
            title="ماشین پروندهٔ تحویل",
            brand="Toyota",
            model="Camry",
            status=Car.Status.SOLD,
            tracking_code="OAL-delivery-dossier",
            customer=self.customer,
        )
        start_tracking_for_sold_car(
            car=self.machine,
            actor=self.administrator,
        )

    def test_superuser_can_append_a_stage_and_tracking_progress_is_backfilled(self):
        self.client.force_login(self.administrator)

        response = self.client.post(
            reverse("backoffice:stage_create"),
            data={
                "name": "تحویل نهایی",
                "duration_from_previous": "2",
                "assigned_staff": [str(self.clearance_profile.pk)],
            },
        )

        created_stage = Stage.objects.get(name="تحویل نهایی")
        self.assertRedirects(response, reverse("backoffice:stage_list"))
        self.assertTrue(
            StageTransition.objects.filter(
                from_stage=self.third_stage,
                to_stage=created_stage,
                estimated_duration_days=2,
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            CarStageProgress.objects.filter(
                car=self.machine,
                stage=created_stage,
                planned_date__isnull=False,
            ).exists()
        )

    def test_delivery_dossier_distinguishes_entered_and_waiting_next_stage(self):
        confirm_stage(
            car=self.machine,
            stage=self.second_stage,
            staff=self.clearance_employee,
        )
        self.client.force_login(self.administrator)

        entered_response = self.client.get(
            reverse("backoffice:delivery_machine_detail", args=[self.machine.pk])
        )
        self.assertContains(entered_response, self.machine.tracking_code)
        self.assertContains(entered_response, "وارد مرحله")
        self.assertContains(entered_response, self.clearance_employee.username)
        self.assertContains(entered_response, "تصویر ماشین ثبت نشده است")

        complete_stage(
            car=self.machine,
            stage=self.second_stage,
            staff=self.clearance_employee,
        )
        waiting_response = self.client.get(
            reverse("backoffice:delivery_machine_detail", args=[self.machine.pk])
        )

        self.assertContains(waiting_response, "منتظر دریافت")
        self.assertContains(waiting_response, self.third_stage.name)
        self.assertContains(waiting_response, self.clearance_employee.username)

    def test_legacy_sold_machine_without_tracking_code_is_explicitly_flagged(self):
        legacy_machine = Car.objects.create(
            title="ماشین فروش دستی",
            brand="Kia",
            model="K5",
            status=Car.Status.SOLD,
            customer=self.customer,
        )
        self.client.force_login(self.administrator)

        response = self.client.get(
            reverse("backoffice:delivery_machine_detail", args=[legacy_machine.pk])
        )

        self.assertContains(response, "کد ثبت نشده")
        self.assertContains(response, "رهگیری هنوز شروع نشده")

    def test_regular_employee_cannot_open_stage_configuration(self):
        user_model = get_user_model()
        employee = user_model.objects.create_user(
            username="ordinary-delivery-employee",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(employee)

        self.assertEqual(
            self.client.get(reverse("backoffice:stage_list")).status_code,
            403,
        )

    def test_system_administrator_can_repair_missing_route_transitions(self):
        """The repair screen removes the legacy configuration dead-end."""

        StageTransition.objects.update(is_active=False)
        self.client.force_login(self.administrator)
        repair_url = reverse("backoffice:stage_transition_repair")

        response = self.client.get(repair_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.first_stage.name)
        self.assertContains(response, self.second_stage.name)

        response = self.client.post(
            repair_url,
            data={
                f"duration_to_stage_{self.second_stage.pk}": "7",
                f"duration_to_stage_{self.third_stage.pk}": "5",
                "confirm_route_repair": "on",
            },
        )

        self.assertRedirects(response, reverse("backoffice:stage_list"))
        self.assertEqual(
            StageTransition.objects.filter(is_active=True).count(),
            2,
        )
        self.second_stage.refresh_from_db()
        self.assertEqual(self.second_stage.default_duration_days, 7)

        first_progress = CarStageProgress.objects.get(
            car=self.machine,
            stage=self.first_stage,
        )
        third_progress = CarStageProgress.objects.get(
            car=self.machine,
            stage=self.third_stage,
        )
        self.assertEqual(
            third_progress.planned_date,
            first_progress.planned_date + timedelta(days=12),
        )


class BackofficeMachinePhotoWorkflowTests(TestCase):
    def setUp(self):
        self.temporary_media = TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.temporary_media.name)
        self.media_override.enable()

        role_groups = ensure_default_role_groups()
        user_model = get_user_model()
        self.employee = user_model.objects.create_user(
            username="backoffice-photo-employee",
            password="test-password",
            is_staff=True,
        )
        self.employee.groups.add(role_groups[RoleGroup.EMPLOYEE])

        self.clearance_employee = user_model.objects.create_user(
            username="backoffice-photo-clearance",
            password="test-password",
            is_staff=True,
        )
        self.clearance_employee.groups.add(
            role_groups[RoleGroup.CLEARANCE_EMPLOYEE]
        )

        self.machine = Car.objects.create(
            title="ماشین تصویر آزمون",
            brand="Toyota",
            model="Camry",
            status=Car.Status.DRAFT,
        )

    def tearDown(self):
        self.media_override.disable()
        self.temporary_media.cleanup()

    @staticmethod
    def make_image_file(name, color):
        image = Image.new("RGB", (320, 220), color=color)
        output = BytesIO()
        image.save(output, format="WEBP", quality=80)

        return SimpleUploadedFile(
            name,
            output.getvalue(),
            content_type="image/webp",
        )

    def test_employee_can_upload_multiple_photos_and_first_image_becomes_cover(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:machine_photo_upload", args=[self.machine.pk]),
            data={
                "images": [
                    self.make_image_file("front.webp", (18, 82, 156)),
                    self.make_image_file("rear.webp", (123, 42, 67)),
                ]
            },
        )

        self.assertRedirects(
            response,
            reverse("backoffice:machine_photo_manage", args=[self.machine.pk]),
        )
        photos = list(CarPhoto.objects.filter(car=self.machine).order_by("sort_order"))
        event = VehicleInventoryEvent.objects.filter(car=self.machine).get()

        self.assertEqual(len(photos), 2)
        self.assertTrue(photos[0].is_cover)
        self.assertFalse(photos[1].is_cover)
        self.assertEqual(event.changes["photos"]["operation"], "added")

    def test_cover_can_change_and_deleting_it_promotes_the_next_photo(self):
        first_photo = CarPhoto.objects.create(
            car=self.machine,
            image=self.make_image_file("first.webp", (40, 60, 80)),
            is_cover=True,
            sort_order=1,
        )
        second_photo = CarPhoto.objects.create(
            car=self.machine,
            image=self.make_image_file("second.webp", (80, 60, 40)),
            sort_order=2,
        )
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse(
                "backoffice:machine_photo_set_cover",
                args=[self.machine.pk, second_photo.pk],
            ),
        )
        self.assertRedirects(
            response,
            reverse("backoffice:machine_photo_manage", args=[self.machine.pk]),
        )

        first_photo.refresh_from_db()
        second_photo.refresh_from_db()
        self.assertFalse(first_photo.is_cover)
        self.assertTrue(second_photo.is_cover)

        response = self.client.post(
            reverse(
                "backoffice:machine_photo_delete",
                args=[self.machine.pk, second_photo.pk],
            ),
        )
        self.assertRedirects(
            response,
            reverse("backoffice:machine_photo_manage", args=[self.machine.pk]),
        )

        first_photo.refresh_from_db()
        self.assertTrue(first_photo.is_cover)
        self.assertFalse(CarPhoto.objects.filter(pk=second_photo.pk).exists())

    def test_clearance_employee_cannot_open_global_machine_media_management(self):
        self.client.force_login(self.clearance_employee)
        gallery_url = reverse(
            "backoffice:machine_photo_manage",
            args=[self.machine.pk],
        )
        upload_url = reverse(
            "backoffice:machine_photo_upload",
            args=[self.machine.pk],
        )

        self.assertEqual(self.client.get(gallery_url).status_code, 403)
        self.assertEqual(
            self.client.post(
                upload_url,
                data={"images": [self.make_image_file("denied.webp", (0, 0, 0))]},
            ).status_code,
            403,
        )
        self.assertEqual(CarPhoto.objects.count(), 0)


class BackofficeBlogWorkflowTests(TestCase):
    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()
        self.employee = user_model.objects.create_user(
            username="backoffice-blog-employee",
            password="test-password",
            is_staff=True,
        )
        self.employee.groups.add(role_groups[RoleGroup.EMPLOYEE])

        self.clearance_employee = user_model.objects.create_user(
            username="backoffice-blog-clearance",
            password="test-password",
            is_staff=True,
        )
        self.clearance_employee.groups.add(
            role_groups[RoleGroup.CLEARANCE_EMPLOYEE]
        )
        self.category = Category.objects.create(
            name="راهنمای واردات",
            slug="import-guide",
        )
        self.post = Post.objects.create(
            title="راهنمای اولیهٔ وبلاگ",
            slug="initial-blog-guide",
            author=self.employee,
            category=self.category,
            excerpt="خلاصهٔ اولیه",
            content="متن اولیهٔ مقاله برای آزمون پنل اختصاصی.",
        )

    def post_payload(self, **overrides):
        payload = {
            "title": "راهنمای خرید خودرو از عمان",
            "slug": "oman-car-buying-guide",
            "category": str(self.category.pk),
            "cover_image_alt": "خودرو در بندر عمان",
            "excerpt": "خلاصهٔ کاربردی برای خریداران خودرو.",
            "content": "متن کامل مقاله دربارهٔ انتخاب و واردات خودرو.",
            "seo_title": "راهنمای SEO خرید خودرو از عمان",
            "meta_description": "توضیح SEO مقالهٔ آزمایشی.",
            "meta_keywords": "خودرو، عمان، واردات",
        }
        payload.update(overrides)
        return payload

    def test_employee_creates_a_draft_article_through_the_shared_service(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:blog_post_create"),
            data=self.post_payload(),
        )

        created_post = Post.objects.get(slug="oman-car-buying-guide")
        self.assertRedirects(
            response,
            reverse("backoffice:blog_post_edit", args=[created_post.pk]),
        )
        self.assertEqual(created_post.author, self.employee)
        self.assertEqual(created_post.status, Post.Status.DRAFT)
        self.assertIsNone(created_post.published_at)

    def test_article_list_searches_only_by_title_and_filters_status(self):
        published_post = Post.objects.create(
            title="راهنمای تخصصی بندر عمان",
            slug="published-port-guide",
            author=self.employee,
            content="متن مقالهٔ منتشرشده.",
            status=Post.Status.PUBLISHED,
        )
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse("backoffice:blog_post_list"),
            {"q": "تخصصی", "status": Post.Status.PUBLISHED},
        )

        self.assertContains(response, published_post.title)
        self.assertNotContains(response, self.post.title)
        self.assertContains(response, "جست‌وجو در عنوان مقاله")

    def test_edit_preserves_author_and_publish_workflow_uses_shared_rules(self):
        self.client.force_login(self.employee)

        edit_response = self.client.post(
            reverse("backoffice:blog_post_edit", args=[self.post.pk]),
            data=self.post_payload(
                title="راهنمای ویرایش‌شدهٔ وبلاگ",
                slug=self.post.slug,
            ),
        )
        self.assertRedirects(
            edit_response,
            reverse("backoffice:blog_post_edit", args=[self.post.pk]),
        )
        self.post.refresh_from_db()
        self.assertEqual(self.post.author, self.employee)
        self.assertEqual(self.post.title, "راهنمای ویرایش‌شدهٔ وبلاگ")

        self.assertEqual(
            self.client.get(
                reverse("backoffice:blog_post_publish", args=[self.post.pk])
            ).status_code,
            405,
        )
        publish_response = self.client.post(
            reverse("backoffice:blog_post_publish", args=[self.post.pk])
        )
        self.assertRedirects(publish_response, reverse("backoffice:blog_post_list"))
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.PUBLISHED)
        self.assertIsNotNone(self.post.published_at)
        self.assertEqual(self.client.get(self.post.get_absolute_url()).status_code, 200)

        unpublish_response = self.client.post(
            reverse("backoffice:blog_post_unpublish", args=[self.post.pk])
        )
        self.assertRedirects(unpublish_response, reverse("backoffice:blog_post_list"))
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.DRAFT)
        self.assertIsNone(self.post.published_at)
        self.assertEqual(self.client.get(self.post.get_absolute_url()).status_code, 404)

    def test_delete_requires_confirmation_and_clearance_employee_is_denied(self):
        self.client.force_login(self.clearance_employee)
        self.assertEqual(
            self.client.get(reverse("backoffice:blog_post_list")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("backoffice:blog_post_create")).status_code,
            403,
        )

        self.client.force_login(self.employee)
        delete_url = reverse("backoffice:blog_post_delete", args=[self.post.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 200)
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())

        response = self.client.post(delete_url)
        self.assertRedirects(response, reverse("backoffice:blog_post_list"))
        self.assertFalse(Post.objects.filter(pk=self.post.pk).exists())

    def test_invalid_cover_upload_does_not_create_an_article(self):
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("backoffice:blog_post_create"),
            data={
                **self.post_payload(slug="invalid-cover-post"),
                "cover_image": SimpleUploadedFile(
                    "not-an-image.jpg",
                    b"not a real image",
                    content_type="image/jpeg",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Post.objects.filter(slug="invalid-cover-post").exists())


class BackofficeStaffManagementTests(TestCase):
    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()
        self.administrator = user_model.objects.create_superuser(
            username="backoffice-staff-administrator",
            password="strong-admin-password-123",
        )
        self.employee = user_model.objects.create_user(
            username="backoffice-staff-employee",
            password="test-password",
            first_name="Ali",
            last_name="Employee",
            is_staff=True,
        )
        self.employee.groups.add(role_groups[RoleGroup.EMPLOYEE])
        StaffProfile.objects.create(user=self.employee, phone="09120000000")
        self.stage = Stage.objects.create(name="Clearance stage", order=1)

    def test_only_system_administrator_can_open_staff_management_pages(self):
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("backoffice:staff_list")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("backoffice:staff_create")).status_code,
            403,
        )

        self.client.force_login(self.administrator)
        response = self.client.get(reverse("backoffice:staff_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "مدیریت کارکنان")
        self.assertContains(response, self.employee.username)
        self.assertContains(
            response,
            reverse("backoffice:staff_detail", args=[self.employee.pk]),
        )

    def test_administrator_creates_staff_account_through_the_panel(self):
        self.client.force_login(self.administrator)

        response = self.client.post(
            reverse("backoffice:staff_create"),
            data={
                "username": "panel-clearance-employee",
                "first_name": "Reza",
                "last_name": "Clearance",
                "email": "reza@example.com",
                "phone": "09123333333",
                "role": "clearance_employee",
                "assigned_stages": [str(self.stage.pk)],
                "exceptional_permissions": [],
                "password1": "Secure-panel-password-123!",
                "password2": "Secure-panel-password-123!",
            },
        )

        created_user = get_user_model().objects.get(
            username="panel-clearance-employee"
        )
        self.assertRedirects(
            response,
            reverse("backoffice:staff_detail", args=[created_user.pk]),
        )
        self.assertTrue(created_user.has_perm("tracking.confirm_tracking_stage"))
        self.assertTrue(
            StaffProfile.objects.get(user=created_user).assigned_stages.filter(
                pk=self.stage.pk
            ).exists()
        )

    def test_administrator_can_create_a_combined_employee_and_clearance_account(self):
        self.client.force_login(self.administrator)
        create_url = reverse("backoffice:staff_create")
        self.assertContains(self.client.get(create_url), "کارمند + کارمند ترخیص")

        response = self.client.post(
            create_url,
            data={
                "username": "panel-combined-employee",
                "first_name": "Sara",
                "last_name": "Operations",
                "email": "sara@example.com",
                "phone": "09124444444",
                "role": "employee_and_clearance",
                "assigned_stages": [str(self.stage.pk)],
                "exceptional_permissions": [],
                "password1": "Secure-panel-password-123!",
                "password2": "Secure-panel-password-123!",
            },
        )

        created_user = get_user_model().objects.get(
            username="panel-combined-employee"
        )
        self.assertRedirects(
            response,
            reverse("backoffice:staff_detail", args=[created_user.pk]),
        )
        self.assertTrue(created_user.has_perm("cars.change_car"))
        self.assertTrue(created_user.has_perm("tracking.confirm_tracking_stage"))

    def test_staff_profile_displays_controlled_telegram_actions(self):
        self.client.force_login(self.administrator)

        response = self.client.get(
            reverse("backoffice:staff_detail", args=[self.employee.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "اتصال Telegram")
        self.assertContains(
            response,
            reverse("backoffice:staff_telegram_link_issue", args=[self.employee.pk]),
        )

    def test_staff_profile_displays_automatically_captured_telegram_ids(self):
        TelegramStaffLink.objects.create(
            user=self.employee,
            telegram_user_id=700001,
            telegram_chat_id=800001,
            telegram_username="linked-employee",
        )
        self.client.force_login(self.administrator)

        response = self.client.get(
            reverse("backoffice:staff_detail", args=[self.employee.pk])
        )

        self.assertContains(response, "700001")
        self.assertContains(response, "800001")


class BackofficeCustomerAndClearanceWorkflowTests(TestCase):
    """Panel adapters must use the pre-existing customer/tracking services."""

    def setUp(self):
        role_groups = ensure_default_role_groups()
        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="customer-panel-employee",
            password="test-password",
            is_staff=True,
        )
        self.employee.groups.add(role_groups[RoleGroup.EMPLOYEE])

        self.clearance_employee = user_model.objects.create_user(
            username="clearance-panel-employee",
            password="test-password",
            is_staff=True,
        )
        self.clearance_employee.groups.add(role_groups[RoleGroup.CLEARANCE_EMPLOYEE])
        self.clearance_profile = StaffProfile.objects.create(user=self.clearance_employee)

        self.first_stage = Stage.objects.create(name="ثبت فروش", order=1)
        self.second_stage = Stage.objects.create(name="ترخیص", order=2)
        StageTransition.objects.create(
            from_stage=self.first_stage,
            to_stage=self.second_stage,
            estimated_duration_days=3,
        )
        self.clearance_profile.assigned_stages.add(self.second_stage)

        self.customer = Customer.objects.create(
            full_name="مشتری پنل",
            phone="09124444444",
            telegram_id="customer-panel-id",
        )
        self.machine = Car.objects.create(
            title="ماشین عملیات ترخیص",
            brand="Toyota",
            model="Camry",
            status=Car.Status.SOLD,
            tracking_code="OAL-PANEL-CLEARANCE",
            customer=self.customer,
        )
        self.administrator = user_model.objects.create_superuser(
            username="customer-panel-admin",
            password="test-password",
            email="admin@example.com",
        )
        start_tracking_for_sold_car(car=self.machine, actor=self.administrator)

        self.vehicle_request = create_custom_vehicle_request(
            full_name="متقاضی خودرو",
            phone="09125555555",
            telegram_id="lead-telegram",
            desired_vehicle_description="شاسی‌بلند سفید با سقف پانوراما",
            preferred_brand="Kia",
            preferred_model="Sportage",
            budget_amount="2500000000",
            source=CustomVehicleRequest.Source.WEBSITE,
        )

    def test_employee_can_search_and_open_custom_request_with_audit_receipt(self):
        self.client.force_login(self.employee)
        list_response = self.client.get(
            reverse("backoffice:custom_vehicle_request_list"), {"q": "Sportage"}
        )
        self.assertContains(list_response, self.vehicle_request.full_name)

        detail_response = self.client.get(
            reverse("backoffice:custom_vehicle_request_detail", args=[self.vehicle_request.pk])
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(
            CustomVehicleRequestReadReceipt.objects.filter(
                vehicle_request=self.vehicle_request,
                employee=self.employee,
            ).exists()
        )

    def test_employee_can_find_customer_by_tracking_code(self):
        self.client.force_login(self.employee)
        response = self.client.get(
            reverse("backoffice:customer_list"), {"q": self.machine.tracking_code}
        )
        self.assertContains(response, self.customer.full_name)
        self.assertContains(
            response,
            reverse("backoffice:customer_detail", args=[self.customer.pk]),
        )

    def test_clearance_employee_confirms_and_completes_from_two_step_screen(self):
        self.client.force_login(self.clearance_employee)
        operation_url = reverse("backoffice:clearance_operation")

        preview_response = self.client.post(
            operation_url,
            {"tracking_code": self.machine.tracking_code, "operation": "enter"},
        )
        self.assertContains(preview_response, self.second_stage.name)
        self.assertContains(preview_response, "ثبت نهایی عملیات")

        confirm_response = self.client.post(
            operation_url,
            {
                "tracking_code": self.machine.tracking_code,
                "operation": "enter",
                "confirm_operation": "on",
            },
        )
        self.assertRedirects(confirm_response, operation_url)
        entered_progress = CarStageProgress.objects.get(
            car=self.machine,
            stage=self.second_stage,
        )
        self.assertIsNotNone(entered_progress.actual_arrival)
        self.assertEqual(entered_progress.confirmed_by, self.clearance_employee)

        complete_preview_response = self.client.post(
            operation_url,
            {"tracking_code": self.machine.tracking_code, "operation": "complete"},
        )
        self.assertContains(complete_preview_response, "تکمیل مرحله")

        complete_response = self.client.post(
            operation_url,
            {
                "tracking_code": self.machine.tracking_code,
                "operation": "complete",
                "confirm_operation": "on",
            },
        )
        self.assertRedirects(complete_response, operation_url)
        entered_progress.refresh_from_db()
        self.assertIsNotNone(entered_progress.completed_at)
        self.assertEqual(entered_progress.completed_by, self.clearance_employee)

    def test_general_employee_cannot_open_clearance_operation(self):
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("backoffice:clearance_operation")).status_code,
            403,
        )


class BackofficeReportingAndAuditTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.administrator = user_model.objects.create_superuser(
            username="reporting-admin",
            password="test-password",
            email="reporting@example.com",
        )
        self.employee = user_model.objects.create_user(
            username="reporting-employee",
            password="test-password",
            is_staff=True,
        )
        self.car = Car.objects.create(
            title="ماشین گزارش‌گیری",
            brand="Toyota",
            model="RAV4",
            tracking_code="OAL-REPORT-001",
            status=Car.Status.FOR_SALE,
        )
        self.stage = Stage.objects.create(name="مرحلهٔ گزارش", order=1)

        VehicleInventoryEvent.objects.create(
            car=self.car,
            action=VehicleInventoryEvent.Action.CREATED,
            performed_by=self.administrator,
            source=VehicleInventoryEvent.Source.BACKOFFICE,
        )
        TrackingEvent.objects.create(
            car=self.car,
            event_type=TrackingEvent.EventType.TRACKING_STARTED,
            new_stage=self.stage,
            performed_by=self.administrator,
            source=TrackingEvent.Source.ADMIN_DASHBOARD,
            note="شروع آزمایشی رهگیری",
        )
        StaffManagementEvent.objects.create(
            staff_user=self.employee,
            performed_by=self.administrator,
            action=StaffManagementEvent.Action.CREATED,
            source=StaffManagementEvent.Source.BACKOFFICE,
        )

    def test_system_administrator_sees_real_dashboard_counts(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("backoffice:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["management_snapshot"]["counts"]["for_sale"], 1)
        self.assertContains(response, "ماشین‌های قابل فروش")
        self.assertContains(response, "آخرین رویدادهای حسابرسی")

    def test_audit_log_unifies_and_filters_immutable_event_sources(self):
        self.client.force_login(self.administrator)
        response = self.client.get(
            reverse("backoffice:audit_log"),
            {"source": "tracking", "q": self.car.tracking_code},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "شروع رهگیری ماشین")
        self.assertContains(response, self.car.title)
        self.assertNotContains(response, "ایجاد حساب کارمند")

    def test_non_administrator_cannot_open_audit_log(self):
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("backoffice:audit_log")).status_code,
            403,
        )


class BackofficeSiteSettingsTests(TestCase):
    def setUp(self):
        self.administrator = get_user_model().objects.create_superuser(
            username="site-settings-admin",
            email="settings@example.com",
            password="test-password",
        )

    def test_superuser_can_open_typed_site_settings_and_header_collection(self):
        self.client.force_login(self.administrator)
        HeaderNavigationItem.objects.create(
            label="خدمات", destination="/services/", sort_order=1,
        )

        dashboard = self.client.get(reverse("backoffice:site_settings"))
        identity = self.client.get(reverse("backoffice:site_identity_settings"))
        header = self.client.get(
            reverse("backoffice:site_collection_list", kwargs={"collection": "header"}),
        )

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(header.status_code, 200)
        self.assertContains(dashboard, "مرکز کنترل وب‌سایت")
        self.assertContains(header, "خدمات")
        self.assertEqual(SiteConfiguration.objects.count(), 1)

    def test_panel_logout_ends_the_authenticated_session(self):
        self.client.force_login(self.administrator)

        response = self.client.post(reverse("backoffice:logout"))

        self.assertRedirects(response, reverse("admin:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_entering_admin_root_is_routed_to_the_shared_panel(self):
        employee = get_user_model().objects.create_user(
            username="panel-only-staff",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(employee)

        response = self.client.get("/admin/")

        self.assertRedirects(response, reverse("backoffice:dashboard"))

    def test_system_administrator_entering_admin_root_is_also_routed_to_panel(self):
        self.client.force_login(self.administrator)

        response = self.client.get("/admin/")

        self.assertRedirects(response, reverse("backoffice:dashboard"))


class BackofficeTelegramManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.administrator = user_model.objects.create_superuser(
            username="telegram-panel-administrator",
            password="test-password",
        )
        self.employee = user_model.objects.create_user(
            username="telegram-panel-employee",
            password="test-password",
            is_staff=True,
        )
        self.failed_outbox = TelegramOutboxMessage.objects.create(
            operation=TelegramOutboxMessage.Operation.SEND_MESSAGE,
            chat_id=700001,
            body="پیام آزمایشی",
            message_type="test_failure",
            idempotency_key="telegram-panel-failed-outbox",
            status=TelegramOutboxMessage.Status.FAILED,
        )
        TelegramInboundUpdate.objects.create(
            telegram_update_id=900001,
            update_type=TelegramInboundUpdate.UpdateType.MESSAGE,
            status=TelegramInboundUpdate.Status.FAILED,
        )

    def test_only_administrator_can_open_console_and_requeue_failed_message(self):
        dashboard_url = reverse("backoffice:telegram_management")
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(dashboard_url).status_code, 403)

        self.client.force_login(self.administrator)
        response = self.client.get(dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "مدیریت Telegram")
        self.assertContains(
            response,
            reverse("backoffice:telegram_outbox_retry", args=[self.failed_outbox.pk]),
        )

        retry_response = self.client.post(
            reverse("backoffice:telegram_outbox_retry", args=[self.failed_outbox.pk]),
        )
        self.assertRedirects(retry_response, dashboard_url)
        self.failed_outbox.refresh_from_db()
        self.assertEqual(self.failed_outbox.status, TelegramOutboxMessage.Status.PENDING)
