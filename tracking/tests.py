from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from django.test import TestCase

from tracking.models import (
    CarStageProgress,
    Stage,
    StageTransition,
    TrackingEvent,
)

from cars.models import Car

from accounts.models import StaffProfile

from tracking.services import (
    archive_stage,
    calculate_remaining_eta_days,
    complete_stage,
    confirm_stage,
    correct_tracking_stage,
    get_public_tracking_data,
    get_stage_archive_impact,
    skip_stage,
    start_tracking_for_sold_car,
)


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
        user_model = get_user_model()
        self.employee = user_model.objects.create_user(
            username="tracking-employee",
            password="test-password",
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

    def test_start_tracking_creates_progress_and_event(self):
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
            status=Car.Status.SOLD,
            tracking_code="OAL-test-tracking-code",
        )

        started_car = start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        first_progress = CarStageProgress.objects.get(
            car=started_car,
            stage=self.stage_one,
        )
        second_progress = CarStageProgress.objects.get(
            car=started_car,
            stage=self.stage_two,
        )

        event = TrackingEvent.objects.get(
            car=started_car,
            event_type=TrackingEvent.EventType.TRACKING_STARTED,
        )

        self.assertEqual(
            started_car.current_stage,
            self.stage_one,
        )
        self.assertIsNotNone(first_progress.actual_arrival)
        self.assertEqual(
            first_progress.confirmed_by,
            self.employee,
        )
        self.assertIsNone(second_progress.actual_arrival)

        self.assertEqual(
            event.event_type,
            TrackingEvent.EventType.TRACKING_STARTED,
        )
        self.assertEqual(event.new_stage, self.stage_one)
        self.assertEqual(event.performed_by, self.employee)

    def test_assigned_clearance_employee_can_confirm_next_stage(self):
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
            status=Car.Status.SOLD,
            tracking_code="OAL-confirm-stage-test",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        staff_profile = StaffProfile.objects.create(
            user=self.employee,
        )
        staff_profile.assigned_stages.add(self.stage_two)

        progress = confirm_stage(
            car=car,
            stage=self.stage_two,
            staff=self.employee,
            source=TrackingEvent.Source.TELEGRAM_BOT,
        )

        car.refresh_from_db()

        self.assertEqual(car.current_stage, self.stage_two)
        self.assertIsNotNone(progress.actual_arrival)
        self.assertEqual(progress.confirmed_by, self.employee)

        event = TrackingEvent.objects.get(
            car=car,
            event_type=TrackingEvent.EventType.STAGE_CONFIRMED,
        )

        self.assertEqual(event.previous_stage, self.stage_one)
        self.assertEqual(event.new_stage, self.stage_two)
        self.assertEqual(
            event.source,
            TrackingEvent.Source.TELEGRAM_BOT,
        )

    def test_unassigned_user_cannot_confirm_stage(self):
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
            status=Car.Status.SOLD,
            tracking_code="OAL-unauthorized-stage-test",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        user_model = get_user_model()

        unauthorized_user = user_model.objects.create_user(
            username="unauthorized-user",
            password="test-password",
        )

        with self.assertRaises(ValidationError):
            confirm_stage(
                car=car,
                stage=self.stage_two,
                staff=unauthorized_user,
            )

    def test_superuser_can_skip_next_stage(self):
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
            status=Car.Status.SOLD,
            tracking_code="OAL-skip-stage-test",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        user_model = get_user_model()

        administrator = user_model.objects.create_superuser(
            username="system-administrator",
            password="test-password",
        )

        progress = skip_stage(
            car=car,
            stage=self.stage_two,
            actor=administrator,
            note="This stage is not required for this shipment.",
        )

        car.refresh_from_db()

        self.assertEqual(progress.state, "skipped")
        self.assertIsNotNone(progress.skipped_at)
        self.assertEqual(progress.skipped_by, administrator)
        self.assertEqual(car.current_stage, self.stage_two)

        event = TrackingEvent.objects.get(
            car=car,
            event_type=TrackingEvent.EventType.STAGE_SKIPPED,
        )

        self.assertEqual(event.previous_stage, self.stage_one)
        self.assertEqual(event.new_stage, self.stage_two)
        self.assertEqual(event.performed_by, administrator)
        self.assertEqual(
            event.note,
            "This stage is not required for this shipment.",
        )

    def test_unprivileged_user_cannot_skip_stage(self):
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
            status=Car.Status.SOLD,
            tracking_code="OAL-skip-not-authorized-test",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        with self.assertRaises(ValidationError):
            skip_stage(
                car=car,
                stage=self.stage_two,
                actor=self.employee,
            )

    def test_superuser_can_correct_vehicle_to_earlier_stage(self):
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
            status=Car.Status.SOLD,
            tracking_code="OAL-correction-test",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        user_model = get_user_model()

        administrator = user_model.objects.create_superuser(
            username="correction-administrator",
            password="test-password",
        )

        confirm_stage(
            car=car,
            stage=self.stage_two,
            staff=administrator,
        )

        complete_stage(
            car=car,
            stage=self.stage_two,
            staff=administrator,
        )

        confirm_stage(
            car=car,
            stage=self.stage_three,
            staff=administrator,
        )

        corrected_progress = correct_tracking_stage(
            car=car,
            stage=self.stage_two,
            actor=administrator,
            note="Stage 3 was confirmed by mistake.",
        )

        car.refresh_from_db()

        stage_three_progress = CarStageProgress.objects.get(
            car=car,
            stage=self.stage_three,
        )

        self.assertEqual(car.current_stage, self.stage_two)
        self.assertIsNotNone(corrected_progress.actual_arrival)
        self.assertEqual(corrected_progress.confirmed_by, administrator)

        self.assertIsNone(stage_three_progress.actual_arrival)
        self.assertIsNone(stage_three_progress.confirmed_by)
        self.assertEqual(stage_three_progress.state, "pending")

        event = TrackingEvent.objects.get(
            car=car,
            event_type=TrackingEvent.EventType.STAGE_CORRECTED,
        )

        self.assertEqual(event.previous_stage, self.stage_three)
        self.assertEqual(event.new_stage, self.stage_two)
        self.assertEqual(
            event.note,
            "Stage 3 was confirmed by mistake.",
        )

    def test_correction_requires_a_note(self):
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
            status=Car.Status.SOLD,
            tracking_code="OAL-correction-note-test",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        user_model = get_user_model()

        administrator = user_model.objects.create_superuser(
            username="note-administrator",
            password="test-password",
        )

        confirm_stage(
            car=car,
            stage=self.stage_two,
            staff=administrator,
        )

        with self.assertRaises(ValidationError):
            correct_tracking_stage(
                car=car,
                stage=self.stage_one,
                actor=administrator,
                note="",
            )

    def test_public_tracking_data_contains_only_safe_tracking_data(self):
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
            year=2024,
            color="White",
            status=Car.Status.SOLD,
            tracking_code="OAL-public-tracking-test",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        data = get_public_tracking_data(
            tracking_code="OAL-public-tracking-test",
        )

        self.assertEqual(
            data["tracking_code"],
            "OAL-public-tracking-test",
        )
        self.assertEqual(
            data["vehicle"]["title"],
            "Toyota Land Cruiser",
        )
        self.assertEqual(
            data["current_stage"]["name"],
            self.stage_one.name,
        )
        self.assertEqual(
            data["remaining_eta_days"],
            8,
        )
        self.assertEqual(len(data["stages"]), 3)

        self.assertNotIn("customer", data)
        self.assertNotIn("phone", data)
        self.assertNotIn("telegram_id", data)
        self.assertNotIn("price_amount", data)

    def test_stage_must_be_completed_before_next_stage(self):
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
            status=Car.Status.SOLD,
            tracking_code="OAL-stage-completion-test",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        staff_profile = StaffProfile.objects.create(
            user=self.employee,
        )
        staff_profile.assigned_stages.add(
            self.stage_two,
            self.stage_three,
        )

        confirm_stage(
            car=car,
            stage=self.stage_two,
            staff=self.employee,
        )

        with self.assertRaises(ValidationError):
            confirm_stage(
                car=car,
                stage=self.stage_three,
                staff=self.employee,
            )

        completed_progress = complete_stage(
            car=car,
            stage=self.stage_two,
            staff=self.employee,
        )

        self.assertEqual(completed_progress.state, "completed")
        self.assertIsNotNone(completed_progress.completed_at)
        self.assertEqual(
            completed_progress.completed_by,
            self.employee,
        )

        self.assertTrue(
            TrackingEvent.objects.filter(
                car=car,
                event_type=TrackingEvent.EventType.STAGE_COMPLETED,
                new_stage=self.stage_two,
            ).exists()
        )

        confirm_stage(
            car=car,
            stage=self.stage_three,
            staff=self.employee,
        )

        car.refresh_from_db()

        self.assertEqual(
            car.current_stage,
            self.stage_three,
        )

    def test_stage_archive_impact_groups_affected_vehicles(self):
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

        staff_profile = StaffProfile.objects.create(
            user=self.employee,
        )
        staff_profile.assigned_stages.add(
            self.stage_two,
            self.stage_three,
        )

        not_reached_car = Car.objects.create(
            title="Not Reached Car",
            brand="Toyota",
            model="Corolla",
            status=Car.Status.SOLD,
            tracking_code="OAL-not-reached",
        )
        start_tracking_for_sold_car(
            car=not_reached_car,
            actor=self.employee,
        )

        entered_car = Car.objects.create(
            title="Entered Car",
            brand="Toyota",
            model="Camry",
            status=Car.Status.SOLD,
            tracking_code="OAL-entered",
        )
        start_tracking_for_sold_car(
            car=entered_car,
            actor=self.employee,
        )
        confirm_stage(
            car=entered_car,
            stage=self.stage_two,
            staff=self.employee,
        )

        completed_car = Car.objects.create(
            title="Completed Car",
            brand="Toyota",
            model="Yaris",
            status=Car.Status.SOLD,
            tracking_code="OAL-completed",
        )
        start_tracking_for_sold_car(
            car=completed_car,
            actor=self.employee,
        )
        confirm_stage(
            car=completed_car,
            stage=self.stage_two,
            staff=self.employee,
        )
        complete_stage(
            car=completed_car,
            stage=self.stage_two,
            staff=self.employee,
        )

        passed_car = Car.objects.create(
            title="Passed Car",
            brand="Toyota",
            model="RAV4",
            status=Car.Status.SOLD,
            tracking_code="OAL-passed",
        )
        start_tracking_for_sold_car(
            car=passed_car,
            actor=self.employee,
        )
        confirm_stage(
            car=passed_car,
            stage=self.stage_two,
            staff=self.employee,
        )
        complete_stage(
            car=passed_car,
            stage=self.stage_two,
            staff=self.employee,
        )
        confirm_stage(
            car=passed_car,
            stage=self.stage_three,
            staff=self.employee,
        )

        impact = get_stage_archive_impact(
            stage=self.stage_two,
        )

        self.assertEqual(
            impact["counts"]["entered_not_completed"],
            1,
        )
        self.assertEqual(
            impact["counts"]["completed_waiting_for_next"],
            1,
        )
        self.assertEqual(
            impact["counts"]["not_reached"],
            1,
        )
        self.assertEqual(
            impact["counts"]["already_passed"],
            1,
        )
        self.assertEqual(
            impact["counts"]["total_affected"],
            3,
        )

    def test_archive_stage_updates_all_affected_vehicles(self):
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

        staff_profile = StaffProfile.objects.create(
            user=self.employee,
        )
        staff_profile.assigned_stages.add(
            self.stage_two,
            self.stage_three,
        )

        def create_sold_car(title, tracking_code):
            car = Car.objects.create(
                title=title,
                brand="Toyota",
                model="Land Cruiser",
                status=Car.Status.SOLD,
                tracking_code=tracking_code,
            )
            start_tracking_for_sold_car(
                car=car,
                actor=self.employee,
            )
            return car

        not_reached_car = create_sold_car(
            "Not Reached Car",
            "OAL-archive-not-reached",
        )

        entered_car = create_sold_car(
            "Entered Car",
            "OAL-archive-entered",
        )
        confirm_stage(
            car=entered_car,
            stage=self.stage_two,
            staff=self.employee,
        )

        completed_car = create_sold_car(
            "Completed Car",
            "OAL-archive-completed",
        )
        confirm_stage(
            car=completed_car,
            stage=self.stage_two,
            staff=self.employee,
        )
        complete_stage(
            car=completed_car,
            stage=self.stage_two,
            staff=self.employee,
        )

        passed_car = create_sold_car(
            "Passed Car",
            "OAL-archive-passed",
        )
        confirm_stage(
            car=passed_car,
            stage=self.stage_two,
            staff=self.employee,
        )
        complete_stage(
            car=passed_car,
            stage=self.stage_two,
            staff=self.employee,
        )
        confirm_stage(
            car=passed_car,
            stage=self.stage_three,
            staff=self.employee,
        )

        user_model = get_user_model()

        administrator = user_model.objects.create_superuser(
            username="archive-administrator",
            password="test-password",
        )

        result = archive_stage(
            stage=self.stage_two,
            actor=administrator,
            replacement_duration_days=8,
            note="Customs Clearance stage was removed.",
            confirm_affected_vehicles=True,
        )

        self.stage_two.refresh_from_db()
        not_reached_car.refresh_from_db()
        entered_car.refresh_from_db()
        completed_car.refresh_from_db()
        passed_car.refresh_from_db()

        self.assertFalse(self.stage_two.is_active)

        bridge_transition = StageTransition.objects.get(
            from_stage=self.stage_one,
            to_stage=self.stage_three,
        )

        self.assertTrue(bridge_transition.is_active)
        self.assertEqual(
            bridge_transition.estimated_duration_days,
            8,
        )

        entered_stage_two_progress = CarStageProgress.objects.get(
            car=entered_car,
            stage=self.stage_two,
        )
        entered_stage_one_progress = CarStageProgress.objects.get(
            car=entered_car,
            stage=self.stage_one,
        )

        self.assertEqual(
            entered_car.current_stage,
            self.stage_one,
        )
        self.assertEqual(
            entered_stage_two_progress.state,
            "skipped",
        )
        self.assertEqual(
            entered_stage_one_progress.state,
            "entered",
        )

        completed_stage_three_progress = CarStageProgress.objects.get(
            car=completed_car,
            stage=self.stage_three,
        )

        self.assertEqual(
            completed_car.current_stage,
            self.stage_three,
        )
        self.assertEqual(
            completed_stage_three_progress.state,
            "pending",
        )

        not_reached_stage_two_progress = CarStageProgress.objects.get(
            car=not_reached_car,
            stage=self.stage_two,
        )

        self.assertEqual(
            not_reached_stage_two_progress.state,
            "skipped",
        )
        self.assertEqual(
            not_reached_car.current_stage,
            self.stage_one,
        )

        self.assertEqual(
            passed_car.current_stage,
            self.stage_three,
        )

        self.assertEqual(
            calculate_remaining_eta_days(not_reached_car),
            8,
        )

        self.assertEqual(
            result["impact"]["counts"]["total_affected"],
            3,
        )

        self.assertEqual(
            TrackingEvent.objects.filter(
                event_type=TrackingEvent.EventType.STAGE_ARCHIVED,
            ).count(),
            3,
        )
