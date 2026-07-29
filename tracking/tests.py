from urllib import response

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from django.core.cache import cache

from django.test import RequestFactory, TestCase, override_settings

from tracking.models import (
    CarStageProgress,
    Stage,
    StageTransition,
    TrackingEvent,
)

from cars.models import Car
from accounts.models import StaffProfile
from accounts.services import RoleGroup, ensure_default_role_groups

from django.contrib.auth.models import Permission

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

from django.urls import reverse

from customers.models import Customer, SearchLog


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

        self.clearance_employee_group = ensure_default_role_groups()[
            RoleGroup.CLEARANCE_EMPLOYEE
        ]

        user_model = get_user_model()

        self.employee = user_model.objects.create_user(
            username="tracking-employee",
            password="test-password",
            is_staff=True,
        )
        self.employee.groups.add(
            self.clearance_employee_group,
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
            is_staff=True,
        )
        unauthorized_user.groups.add(
            self.clearance_employee_group,
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

    def test_authorized_employee_can_skip_stage_with_explicit_permission(self):
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
            title="Authorized Skip Car",
            brand="Toyota",
            model="Land Cruiser",
            status=Car.Status.SOLD,
            tracking_code="OAL-authorized-skip",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        user_model = get_user_model()

        authorized_employee = user_model.objects.create_user(
            username="authorized-skip-employee",
            password="test-password",
            is_staff=True,
        )

        skip_permission = Permission.objects.get(
            content_type__app_label="tracking",
            codename="skip_tracking_stage",
        )
        authorized_employee.user_permissions.add(skip_permission)

        progress = skip_stage(
            car=car,
            stage=self.stage_two,
            actor=authorized_employee,
            note="این مرحله برای این خودرو لازم نیست.",
        )

        self.assertEqual(progress.state, "skipped")
        self.assertEqual(progress.skipped_by, authorized_employee)

    def test_inactive_employee_cannot_skip_stage_even_with_permission(self):
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
            title="Inactive Skip Car",
            brand="Toyota",
            model="Land Cruiser",
            status=Car.Status.SOLD,
            tracking_code="OAL-inactive-skip",
        )

        start_tracking_for_sold_car(
            car=car,
            actor=self.employee,
        )

        user_model = get_user_model()

        inactive_employee = user_model.objects.create_user(
            username="inactive-skip-employee",
            password="test-password",
            is_staff=True,
            is_active=False,
        )

        skip_permission = Permission.objects.get(
            content_type__app_label="tracking",
            codename="skip_tracking_stage",
        )
        inactive_employee.user_permissions.add(skip_permission)

        with self.assertRaises(ValidationError):
            skip_stage(
                car=car,
                stage=self.stage_two,
                actor=inactive_employee,
            )

        car.refresh_from_db()

        self.assertEqual(car.current_stage, self.stage_one)

    def test_change_stage_permission_cannot_archive_a_stage(self):
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

        user_model = get_user_model()

        generic_stage_editor = user_model.objects.create_user(
            username="generic-stage-editor",
            password="test-password",
            is_staff=True,
        )

        generic_change_permission = Permission.objects.get(
            content_type__app_label="tracking",
            codename="change_stage",
        )
        generic_stage_editor.user_permissions.add(
            generic_change_permission,
        )

        with self.assertRaises(ValidationError):
            archive_stage(
                stage=self.stage_two,
                actor=generic_stage_editor,
                replacement_duration_days=8,
                note="آزمایش مجوز Archive",
                confirm_affected_vehicles=True,
            )

        self.stage_two.refresh_from_db()

        self.assertTrue(self.stage_two.is_active)

    def test_authorized_employee_can_archive_stage_with_explicit_permission(self):
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

        user_model = get_user_model()

        authorized_employee = user_model.objects.create_user(
            username="authorized-archive-employee",
            password="test-password",
            is_staff=True,
        )

        archive_permission = Permission.objects.get(
            content_type__app_label="tracking",
            codename="archive_tracking_stage",
        )
        authorized_employee.user_permissions.add(archive_permission)

        result = archive_stage(
            stage=self.stage_two,
            actor=authorized_employee,
            replacement_duration_days=8,
            note="آزمایش Archive مجاز",
            confirm_affected_vehicles=True,
        )

        self.stage_two.refresh_from_db()

        self.assertFalse(self.stage_two.is_active)
        self.assertEqual(
            result["impact"]["counts"]["total_affected"],
            0,
        )


class PublicTrackingLookupViewTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="public-tracking-actor",
            password="test-password",
        )

        self.sale_confirmed_stage = Stage.objects.create(
            name="Sale Confirmed",
            order=1,
        )
        self.shipping_stage = Stage.objects.create(
            name="Shipping from Oman",
            order=2,
        )

        StageTransition.objects.create(
            from_stage=self.sale_confirmed_stage,
            to_stage=self.shipping_stage,
            estimated_duration_days=5,
        )

        self.customer = Customer.objects.create(
            full_name="Private Customer Name",
            phone="09123456789",
            telegram_id="private_customer_telegram_id",
        )

        self.car = Car.objects.create(
            title="2024 Toyota Camry",
            brand="Toyota",
            model="Camry",
            year=2024,
            color="White",
            price_amount=3_000_000_000,
            status=Car.Status.SOLD,
            customer=self.customer,
            tracking_code="OAL-public-tracking-test-code",
        )

        start_tracking_for_sold_car(
            car=self.car,
            actor=self.actor,
        )

    def test_get_displays_the_public_tracking_lookup_form(self):
        response = self.client.get(reverse("tracking:public_lookup"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "tracking/public_lookup.html",
        )
        self.assertContains(
            response,
            'name="tracking_code"',
            html=False,
        )

    def test_valid_tracking_code_displays_safe_tracking_data(self):
        response = self.client.post(
            reverse("tracking:public_lookup"),
            data={
                "tracking_code": self.car.tracking_code,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["tracking_data"]["tracking_code"],
            self.car.tracking_code,
        )
        self.assertEqual(
            response.context["tracking_data"]["remaining_eta_days"],
            5,
        )

        self.assertContains(response, self.car.title)
        self.assertContains(response, self.sale_confirmed_stage.name)

        # Public tracking must not expose private customer or financial data.
        self.assertNotContains(response, self.customer.full_name)
        self.assertNotContains(response, self.customer.phone)
        self.assertNotContains(response, self.customer.telegram_id)
        self.assertNotContains(response, "3,000,000,000")

    def test_unknown_tracking_code_shows_a_generic_error(self):
        response = self.client.post(
            reverse("tracking:public_lookup"),
            data={
                "tracking_code": "OAL-unknown-code",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["tracking_data"])
        self.assertContains(
            response,
            "اطلاعات رهگیری با این کد پیدا نشد.",
        )

        # Do not expose the internal service/database error to the visitor.
        self.assertNotContains(
            response,
            "هیچ سابقه پیگیری برای این کد یافت نشد.",
        )

    def test_successful_web_lookup_creates_a_search_log(self):
        response = self.client.post(
            reverse("tracking:public_lookup"),
            data={
                "tracking_code": self.car.tracking_code,
            },
            HTTP_USER_AGENT="Phase 4 test browser",
        )

        self.assertEqual(response.status_code, 200)

        search_log = SearchLog.objects.get()

        self.assertEqual(search_log.car, self.car)
        self.assertEqual(search_log.customer, self.customer)
        self.assertEqual(search_log.source, SearchLog.Source.WEB)
        self.assertEqual(
            search_log.user_agent,
            "Phase 4 test browser",
        )

    def test_unknown_tracking_code_is_not_logged(self):
        response = self.client.post(
            reverse("tracking:public_lookup"),
            data={
                "tracking_code": "OAL-unknown-code",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SearchLog.objects.count(), 0)


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "public-tracking-rate-limit-tests",
        }
    },
    PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS=3,
    PUBLIC_TRACKING_RATE_LIMIT_WINDOW_SECONDS=60,
)
class PublicTrackingRateLimitTests(TestCase):
    def setUp(self):
        # This clears only the temporary in-memory cache used by this test class.
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_fourth_tracking_lookup_from_same_ip_is_rate_limited(self):
        url = reverse("tracking:public_lookup")
        client_ip = "203.0.113.10"

        for attempt_number in range(3):
            response = self.client.post(
                url,
                data={
                    "tracking_code": f"OAL-rate-limit-{attempt_number}",
                },
                REMOTE_ADDR=client_ip,
            )

            self.assertEqual(response.status_code, 200)
            self.assertContains(
                response,
                "اطلاعات رهگیری با این کد پیدا نشد.",
            )

        blocked_response = self.client.post(
            url,
            data={
                "tracking_code": "OAL-rate-limit-blocked",
            },
            REMOTE_ADDR=client_ip,
        )

        self.assertEqual(blocked_response.status_code, 200)
        self.assertContains(
            blocked_response,
            "تعداد تلاش‌های شما بیش از حد مجاز است. لطفاً چند دقیقه دیگر دوباره تلاش کنید.",
        )
        self.assertEqual(SearchLog.objects.count(), 0)


class TrackingAdminSafetyTests(TestCase):
    def setUp(self):
        user_model = get_user_model()

        self.administrator = user_model.objects.create_superuser(
            username="tracking-admin-safety",
            password="test-password",
        )

        request_factory = RequestFactory()
        self.request = request_factory.get("/admin/")
        self.request.user = self.administrator

        self.stage_admin = admin.site._registry[Stage]
        self.progress_admin = admin.site._registry[CarStageProgress]

    def test_tracking_progress_records_cannot_be_mutated_in_admin(self):
        self.assertFalse(self.progress_admin.has_add_permission(self.request))
        self.assertFalse(self.progress_admin.has_change_permission(self.request))
        self.assertFalse(self.progress_admin.has_delete_permission(self.request))

    def test_stage_cannot_be_directly_archived_or_deleted_in_admin(self):
        self.assertIn(
            "is_active",
            self.stage_admin.readonly_fields,
        )
        self.assertFalse(self.stage_admin.has_delete_permission(self.request))
