from django.core.exceptions import ValidationError
from django.test import TestCase

from tracking.models import Stage, StageTransition, TrackingEvent

from cars.models import Car
from tracking.services import calculate_remaining_eta_days


class StageTransitionTests(TestCase):
    def setUp(self):
        self.stage_one = Stage.objects.create(
            name="Vehicle Purchased",
            order=1,
        )
        self.stage_two = Stage.objects.create(
            name="Shipping from Oman",
            order=2,
        )
        self.stage_three = Stage.objects.create(
            name="Customs Clearance",
            order=3,
        )

    def test_forward_transition_is_valid(self):
        transition = StageTransition(
            from_stage=self.stage_one,
            to_stage=self.stage_two,
            estimated_duration_days=3,
        )

        transition.full_clean()
        transition.save()

        self.assertEqual(
            transition.estimated_duration_days,
            3,
        )

    def test_backward_transition_is_invalid(self):
        transition = StageTransition(
            from_stage=self.stage_three,
            to_stage=self.stage_one,
            estimated_duration_days=3,
        )

        with self.assertRaises(ValidationError):
            transition.full_clean()

    def test_stage_cannot_transition_to_itself(self):
        transition = StageTransition(
            from_stage=self.stage_one,
            to_stage=self.stage_one,
            estimated_duration_days=0,
        )

        with self.assertRaises(ValidationError):
            transition.full_clean()

    def test_remaining_eta_is_calculated_from_current_stage(self):
        StageTransition.objects.create(
            from_stage=self.stage_one,
            to_stage=self.stage_two,
            estimated_duration_days=3,
        )
        StageTransition.objects.create(
            from_stage=self.stage_two,
            to_stage=self.stage_three,
            estimated_duration_days=5,
        )

        car = Car.objects.create(
            title="Toyota Land Cruiser",
            brand="Toyota",
            model="Land Cruiser",
            current_stage=self.stage_two,
        )

        remaining_days = calculate_remaining_eta_days(car)

        self.assertEqual(remaining_days, 5)

    def test_tracking_event_cannot_be_updated_or_deleted(self):
    car = Car.objects.create(
        title="Toyota Land Cruiser",
        brand="Toyota",
        model="Land Cruiser",
    )

    event = TrackingEvent.objects.create(
        car=car,
        event_type=TrackingEvent.EventType.TRACKING_STARTED,
        new_stage=self.stage_one,
        source=TrackingEvent.Source.SYSTEM,
        note="Vehicle sale was confirmed.",
    )

    event.note = "This change should not be allowed."

    with self.assertRaises(ValidationError):
        event.save()

    event.refresh_from_db()

    self.assertEqual(
        event.note,
        "Vehicle sale was confirmed.",
    )

    with self.assertRaises(ValidationError):
        event.delete()

    self.assertTrue(TrackingEvent.objects.filter(pk=event.pk).exists())
