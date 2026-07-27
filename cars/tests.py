from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from cars.models import Car, VehicleHold
from cars.services import (
    generate_tracking_code,
    mark_vehicle_as_sold,
    place_vehicle_on_hold,
    publish_vehicle_for_sale,
    release_vehicle_hold,
)
from tracking.models import (
    CarStageProgress,
    Stage,
    StageTransition,
    TrackingEvent,
)


class VehicleHoldServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="employee",
            password="test-password",
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
        self.assertFalse(Car.objects.filter(tracking_code=tracking_code).exists())

    def test_publish_draft_vehicle_for_sale(self):
        self.car.status = Car.Status.DRAFT
        self.car.save(update_fields=["status"])

        published_car = publish_vehicle_for_sale(
            car_id=self.car.id,
        )

        self.assertEqual(
            published_car.status,
            Car.Status.FOR_SALE,
        )

    def test_place_vehicle_on_hold_creates_hold_and_changes_status(self):
        hold = place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.employee,
            customer_name="Test Customer",
            customer_phone="09120000000",
        )

        self.car.refresh_from_db()

        self.assertTrue(hold.is_active)
        self.assertEqual(hold.car, self.car)
        self.assertEqual(hold.created_by, self.employee)
        self.assertEqual(self.car.status, Car.Status.ON_HOLD)

    def test_release_vehicle_hold_returns_car_to_for_sale(self):
        hold = place_vehicle_on_hold(
            car_id=self.car.id,
            actor=self.employee,
        )

        released_hold = release_vehicle_hold(
            hold_id=hold.id,
            actor=self.employee,
            release_note="Customer decided not to buy.",
        )

        self.car.refresh_from_db()

        self.assertFalse(released_hold.is_active)
        self.assertEqual(released_hold.released_by, self.employee)
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
                actor=self.employee,
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
            actor=self.employee,
            customer_name="Test Customer",
            customer_phone="09120000000",
        )

        sold_car = mark_vehicle_as_sold(
            car_id=self.car.id,
            actor=self.employee,
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

        self.assertFalse(hold.is_active)
        self.assertEqual(hold.release_note, "Converted to sold.")

        self.assertEqual(
            sold_car.current_stage,
            sale_confirmed_stage,
        )

        self.assertEqual(
            CarStageProgress.objects.filter(car=sold_car).count(),
            2,
        )

        self.assertTrue(
            TrackingEvent.objects.filter(
                car=sold_car,
                event_type=TrackingEvent.EventType.TRACKING_STARTED,
            ).exists()
        )
