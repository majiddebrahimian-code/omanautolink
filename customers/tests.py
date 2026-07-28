from decimal import Decimal


from django.urls import reverse

from django.core.exceptions import ValidationError
from django.test import TestCase


from cars.models import Car
from cars.services import place_vehicle_on_hold

from tracking.models import Stage

from customers.models import (
    Customer,
    CustomVehicleRequest,
    CustomVehicleRequestReadReceipt,
)

from customers.services import (
    create_custom_vehicle_request,
    convert_custom_vehicle_request_to_sold,
    record_custom_vehicle_request_view,
)

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission


class CustomVehicleRequestServiceTests(TestCase):
    def valid_request_data(self, **overrides):
        data = {
            "full_name": "Ali Ahmadi",
            "phone": "09123456789",
            "telegram_id": "",
            "desired_vehicle_description": (
                "A white family SUV with a panoramic roof and low mileage."
            ),
            "preferred_brand": "Toyota",
            "preferred_model": "Land Cruiser",
            "preferred_year_from": 2020,
            "preferred_year_to": 2024,
            "budget_amount": Decimal("3500000000"),
            "preferred_color": "White",
            "notes": "Panoramic roof is preferred.",
            "source": CustomVehicleRequest.Source.WEBSITE,
        }

        data.update(overrides)

        return data

    def test_create_custom_vehicle_request_stores_customer_requirements(self):
        vehicle_request = create_custom_vehicle_request(**self.valid_request_data())

        self.assertEqual(
            vehicle_request.full_name,
            "Ali Ahmadi",
        )
        self.assertEqual(
            vehicle_request.phone,
            "09123456789",
        )
        self.assertEqual(
            vehicle_request.preferred_brand,
            "Toyota",
        )
        self.assertEqual(
            vehicle_request.preferred_model,
            "Land Cruiser",
        )
        self.assertEqual(
            vehicle_request.preferred_year_from,
            2020,
        )
        self.assertEqual(
            vehicle_request.preferred_year_to,
            2024,
        )
        self.assertEqual(
            vehicle_request.budget_amount,
            Decimal("3500000000"),
        )
        self.assertEqual(
            vehicle_request.source,
            CustomVehicleRequest.Source.WEBSITE,
        )
        self.assertEqual(
            vehicle_request.status,
            CustomVehicleRequest.Status.NEW,
        )
        self.assertIsNone(vehicle_request.sold_car)

        # A lead must not become a Customer before a sale is confirmed.
        self.assertEqual(Customer.objects.count(), 0)

    def test_custom_vehicle_request_rejects_an_invalid_year_range(self):
        with self.assertRaises(ValidationError):
            create_custom_vehicle_request(
                **self.valid_request_data(
                    preferred_year_from=2025,
                    preferred_year_to=2020,
                )
            )

    def test_custom_vehicle_request_rejects_a_non_positive_budget(self):
        with self.assertRaises(ValidationError):
            create_custom_vehicle_request(
                **self.valid_request_data(
                    budget_amount=Decimal("0"),
                )
            )


class CustomVehicleRequestReadReceiptTests(TestCase):
    def setUp(self):
        self.vehicle_request = create_custom_vehicle_request(
            full_name="Sara Hosseini",
            phone="09351234567",
            desired_vehicle_description=(
                "A reliable white family SUV with low mileage."
            ),
            preferred_brand="",
            preferred_model="",
            preferred_year_from=2020,
            preferred_year_to=2024,
            budget_amount=Decimal("2500000000"),
            preferred_color="White",
            notes="",
        )

        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="request-employee",
            password="test-password",
            is_staff=True,
        )

        view_permission = Permission.objects.get(
            codename="view_customvehiclerequest",
        )

        self.employee.user_permissions.add(view_permission)

    def test_authorized_employee_view_creates_one_read_receipt(self):
        receipt = record_custom_vehicle_request_view(
            vehicle_request_id=self.vehicle_request.id,
            employee=self.employee,
        )

        self.assertEqual(
            receipt.vehicle_request,
            self.vehicle_request,
        )
        self.assertEqual(
            receipt.employee,
            self.employee,
        )
        self.assertEqual(
            CustomVehicleRequestReadReceipt.objects.count(),
            1,
        )

        repeated_receipt = record_custom_vehicle_request_view(
            vehicle_request_id=self.vehicle_request.id,
            employee=self.employee,
        )

        self.assertEqual(
            repeated_receipt.pk,
            receipt.pk,
        )
        self.assertEqual(
            CustomVehicleRequestReadReceipt.objects.count(),
            1,
        )

    def test_employee_without_view_permission_cannot_create_receipt(self):
        user_model = get_user_model()

        unauthorized_employee = user_model.objects.create_user(
            username="unauthorized-employee",
            password="test-password",
            is_staff=True,
        )

        with self.assertRaises(ValidationError):
            record_custom_vehicle_request_view(
                vehicle_request_id=self.vehicle_request.id,
                employee=unauthorized_employee,
            )


class CustomVehicleRequestConversionTests(TestCase):
    def setUp(self):
        self.sale_confirmed_stage = Stage.objects.create(
            name="Sale Confirmed",
            order=1,
        )

        user_model = get_user_model()

        self.authorized_employee = user_model.objects.create_user(
            username="sales-employee",
            password="test-password",
            is_staff=True,
        )

        change_permission = Permission.objects.get(
            codename="change_customvehiclerequest",
        )

        self.authorized_employee.user_permissions.add(change_permission)

        self.vehicle_request = create_custom_vehicle_request(
            full_name="Reza Mohammadi",
            phone="09121234567",
            desired_vehicle_description=("A reliable white SUV with low mileage."),
            preferred_brand="Toyota",
            preferred_model="Land Cruiser",
            preferred_year_from=2020,
            preferred_year_to=2024,
            budget_amount=Decimal("3500000000"),
            preferred_color="White",
            notes="",
        )

        self.car = Car.objects.create(
            title="2023 Toyota Land Cruiser",
            brand="Toyota",
            model="Land Cruiser",
            year=2023,
            color="White",
            price_amount=3_400_000_000,
            status=Car.Status.FOR_SALE,
        )

        place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.authorized_employee,
            customer_name=self.vehicle_request.full_name,
            customer_phone=self.vehicle_request.phone,
        )

    def test_authorized_employee_converts_request_to_sold_vehicle(self):
        sold_car = convert_custom_vehicle_request_to_sold(
            vehicle_request_id=self.vehicle_request.id,
            car_id=self.car.id,
            actor=self.authorized_employee,
            telegram_id="reza_customer_telegram_id",
        )

        self.vehicle_request.refresh_from_db()
        sold_car.refresh_from_db()

        self.assertEqual(
            sold_car.status,
            Car.Status.SOLD,
        )
        self.assertEqual(
            sold_car.customer.full_name,
            "Reza Mohammadi",
        )
        self.assertEqual(
            sold_car.customer.phone,
            "09121234567",
        )
        self.assertEqual(
            sold_car.customer.telegram_id,
            "reza_customer_telegram_id",
        )
        self.assertTrue(sold_car.tracking_code)
        self.assertEqual(
            sold_car.current_stage,
            self.sale_confirmed_stage,
        )

        self.assertEqual(
            self.vehicle_request.status,
            CustomVehicleRequest.Status.SOLD,
        )
        self.assertEqual(
            self.vehicle_request.sold_car,
            sold_car,
        )
        self.assertEqual(
            self.vehicle_request.sold_by,
            self.authorized_employee,
        )
        self.assertEqual(
            self.vehicle_request.telegram_id,
            "reza_customer_telegram_id",
        )
        self.assertIsNotNone(
            self.vehicle_request.sold_at,
        )

    def test_employee_without_permission_cannot_convert_request_to_sale(self):
        user_model = get_user_model()

        unauthorized_employee = user_model.objects.create_user(
            username="unauthorized-sales-employee",
            password="test-password",
            is_staff=True,
        )

        with self.assertRaises(ValidationError):
            convert_custom_vehicle_request_to_sold(
                vehicle_request_id=self.vehicle_request.id,
                car_id=self.car.id,
                actor=unauthorized_employee,
                telegram_id="reza_customer_telegram_id",
            )

        self.vehicle_request.refresh_from_db()
        self.car.refresh_from_db()

        self.assertEqual(
            self.vehicle_request.status,
            CustomVehicleRequest.Status.NEW,
        )
        self.assertEqual(
            self.car.status,
            Car.Status.ON_HOLD,
        )


class PublicCustomVehicleRequestViewTests(TestCase):
    def valid_form_data(self, **overrides):
        data = {
            "full_name": "Maryam Karimi",
            "phone": "09135555555",
            "telegram_id": "",
            "desired_vehicle_description": (
                "A white family SUV with a panoramic roof."
            ),
            "preferred_brand": "",
            "preferred_model": "",
            "preferred_year_from": "2020",
            "preferred_year_to": "2024",
            "budget_amount": "3000000000",
            "preferred_color": "White",
            "notes": "Low mileage is important.",
        }

        data.update(overrides)

        return data

    def test_get_displays_custom_vehicle_request_form(self):
        response = self.client.get(reverse("customers:custom_vehicle_request_create"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "customers/custom_vehicle_request_form.html",
        )
        self.assertContains(
            response,
            'name="desired_vehicle_description"',
            html=False,
        )

    def test_valid_post_creates_new_custom_vehicle_request(self):
        response = self.client.post(
            reverse("customers:custom_vehicle_request_create"),
            data=self.valid_form_data(),
        )

        self.assertRedirects(
            response,
            reverse("customers:custom_vehicle_request_success"),
        )

        vehicle_request = CustomVehicleRequest.objects.get()

        self.assertEqual(
            vehicle_request.full_name,
            "Maryam Karimi",
        )
        self.assertEqual(
            vehicle_request.source,
            CustomVehicleRequest.Source.WEBSITE,
        )
        self.assertEqual(
            vehicle_request.status,
            CustomVehicleRequest.Status.NEW,
        )
        self.assertEqual(Customer.objects.count(), 0)

    def test_invalid_year_range_displays_persian_error_and_creates_nothing(self):
        response = self.client.post(
            reverse("customers:custom_vehicle_request_create"),
            data=self.valid_form_data(
                preferred_year_from="2025",
                preferred_year_to="2020",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "سال پایان نمی‌تواند از سال شروع کمتر باشد.",
        )
        self.assertEqual(
            CustomVehicleRequest.objects.count(),
            0,
        )


class CustomVehicleRequestAdminAuditTests(TestCase):
    def setUp(self):
        self.vehicle_request = create_custom_vehicle_request(
            full_name="Nima Ebrahimi",
            phone="09127777777",
            desired_vehicle_description=(
                "A low-mileage family SUV with a panoramic roof."
            ),
            preferred_brand="",
            preferred_model="",
            preferred_year_from=2020,
            preferred_year_to=2024,
            budget_amount=Decimal("2800000000"),
            preferred_color="",
            notes="",
        )

        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="admin-view-employee",
            password="test-password",
            is_staff=True,
        )

        view_permission = Permission.objects.get(
            codename="view_customvehiclerequest",
        )

        self.employee.user_permissions.add(view_permission)

        self.client.force_login(self.employee)

    def test_opening_request_in_admin_creates_read_receipt(self):
        response = self.client.get(
            reverse(
                "admin:customers_customvehiclerequest_change",
                args=[self.vehicle_request.id],
            )
        )

        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            CustomVehicleRequestReadReceipt.objects.filter(
                vehicle_request=self.vehicle_request,
                employee=self.employee,
            ).exists()
        )


class CustomVehicleRequestAdminConversionTests(TestCase):
    def setUp(self):
        self.sale_confirmed_stage = Stage.objects.create(
            name="Sale Confirmed",
            order=1,
        )

        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="admin-sales-employee",
            password="test-password",
            is_staff=True,
        )

        view_permission = Permission.objects.get(
            codename="view_customvehiclerequest",
        )
        change_permission = Permission.objects.get(
            codename="change_customvehiclerequest",
        )

        self.employee.user_permissions.add(
            view_permission,
            change_permission,
        )

        self.vehicle_request = create_custom_vehicle_request(
            full_name="Hossein Rahimi",
            phone="09128888888",
            desired_vehicle_description=("A low-mileage white Toyota Land Cruiser."),
            preferred_brand="Toyota",
            preferred_model="Land Cruiser",
            preferred_year_from=2020,
            preferred_year_to=2024,
            budget_amount=Decimal("3500000000"),
            preferred_color="White",
            notes="",
        )

        self.car = Car.objects.create(
            title="2023 Toyota Land Cruiser",
            brand="Toyota",
            model="Land Cruiser",
            year=2023,
            color="White",
            price_amount=3_400_000_000,
            status=Car.Status.FOR_SALE,
        )

        place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.employee,
            customer_name=self.vehicle_request.full_name,
            customer_phone=self.vehicle_request.phone,
        )

        self.client.force_login(self.employee)

    def test_admin_conversion_page_displays_held_car_and_telegram_fields(self):
        response = self.client.get(
            reverse(
                "admin:customers_customvehiclerequest_convert_to_sale",
                args=[self.vehicle_request.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'name="car"',
            html=False,
        )
        self.assertContains(
            response,
            'name="telegram_id"',
            html=False,
        )

    def test_admin_conversion_post_marks_request_and_car_as_sold(self):
        response = self.client.post(
            reverse(
                "admin:customers_customvehiclerequest_convert_to_sale",
                args=[self.vehicle_request.id],
            ),
            data={
                "car": self.car.id,
                "telegram_id": "hossein_customer_telegram_id",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "admin:customers_customvehiclerequest_change",
                args=[self.vehicle_request.id],
            ),
        )

        self.vehicle_request.refresh_from_db()
        self.car.refresh_from_db()

        self.assertEqual(
            self.vehicle_request.status,
            CustomVehicleRequest.Status.SOLD,
        )
        self.assertEqual(
            self.vehicle_request.sold_car,
            self.car,
        )
        self.assertEqual(
            self.car.status,
            Car.Status.SOLD,
        )
        self.assertTrue(self.car.tracking_code)
