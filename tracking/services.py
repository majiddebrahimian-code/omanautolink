from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.authorization import (
    require_permission,
    require_stage_confirmation_permission,
)


from .models import (
    CarStageProgress,
    Stage,
    StageTransition,
    TrackingEvent,
)


def _validate_tracking_source(source):
    if source not in TrackingEvent.Source.values:
        raise ValidationError("Invalid tracking source.")


def _ensure_stage_confirmation_permission(*, actor, stage):
    """
    Delegates stage-confirmation authorization to the shared
    authorization layer.
    """

    require_stage_confirmation_permission(
        actor=actor,
        stage=stage,
    )


def _get_next_expected_stage(car):
    """
    Returns the stage that should be entered next.

    If the current workflow stage is pending, that same stage is the
    expected stage to enter.

    If the current stage is completed or skipped, the next active
    stage becomes the expected stage.
    """

    if car.current_stage is None:
        raise ValidationError("Tracking has not started for this vehicle.")

    current_progress = CarStageProgress.objects.select_for_update().get(
        car=car,
        stage=car.current_stage,
    )

    if current_progress.state == "pending":
        return car.current_stage

    if current_progress.state == "entered":
        raise ValidationError(
            "The current stage must be completed before moving " "to the next stage."
        )

    next_stage = (
        Stage.objects.filter(
            is_active=True,
            order__gt=car.current_stage.order,
        )
        .order_by("order")
        .first()
    )

    if next_stage is None:
        raise ValidationError("This vehicle is already at the final tracking stage.")

    return next_stage


@transaction.atomic
def get_stage_confirmation_preview(*, tracking_code, staff):
    """
    Resolves the one stage a staff member may enter next for a vehicle.

    This is intentionally a read/preview service.  Website forms, Telegram
    handlers, and future APIs can ask the same business layer what the next
    valid stage is without copying workflow or authorization rules.
    The final state change must still go through ``confirm_stage``.
    """

    normalized_code = str(tracking_code or "").strip()

    if not normalized_code:
        raise ValidationError("کد رهگیری را وارد کنید.")

    from cars.models import Car

    try:
        car = Car.objects.select_for_update().get(
            tracking_code=normalized_code,
            is_deleted=False,
        )
    except Car.DoesNotExist:
        raise ValidationError("خودرویی با این کد رهگیری پیدا نشد.")

    expected_stage = _get_next_expected_stage(car)

    _ensure_stage_confirmation_permission(
        actor=staff,
        stage=expected_stage,
    )

    return {
        "car": car,
        "stage": expected_stage,
    }


def _get_transition_map(stages):
    transitions = StageTransition.objects.filter(
        is_active=True,
        from_stage__in=stages,
        to_stage__in=stages,
    )

    return {
        (transition.from_stage_id, transition.to_stage_id): transition
        for transition in transitions
    }


def _get_required_transition(transition_map, from_stage, to_stage):
    transition = transition_map.get((from_stage.id, to_stage.id))

    if transition is None:
        raise ValidationError(
            f"No active transition is configured from "
            f"'{from_stage.name}' to '{to_stage.name}'."
        )

    return transition


def get_delay_days(progress):
    """
    Returns the difference between actual arrival and planned arrival.

    Positive value: delayed
    Negative value: earlier than planned
    None: vehicle has not entered the stage yet
    """

    if progress.actual_arrival is None or progress.planned_date is None:
        return None

    return (progress.actual_arrival.date() - progress.planned_date).days


def calculate_remaining_eta_days(car):
    """
    Calculates the dynamic estimated remaining delivery time.
    """

    if car.current_stage is None:
        return None

    stages = list(
        Stage.objects.filter(
            is_active=True,
            order__gte=car.current_stage.order,
        ).order_by("order")
    )

    if not stages or stages[0].id != car.current_stage_id:
        raise ValidationError(
            "The vehicle current stage is not an active tracking stage."
        )

    transition_map = _get_transition_map(stages)

    total_days = 0

    for index in range(len(stages) - 1):
        transition = _get_required_transition(
            transition_map,
            stages[index],
            stages[index + 1],
        )
        total_days += transition.estimated_duration_days

    return total_days


@transaction.atomic
def start_tracking_for_sold_car(
    *,
    car,
    actor,
    source=TrackingEvent.Source.SYSTEM,
):
    """
    Starts tracking for a sold vehicle.

    The first active stage is entered and completed automatically.
    This first stage represents Sale Confirmed.
    """

    _validate_tracking_source(source)

    locked_car = car.__class__.objects.select_for_update().get(pk=car.pk)

    if locked_car.status != locked_car.Status.SOLD:
        raise ValidationError("Tracking can only start for a sold vehicle.")

    if not locked_car.tracking_code:
        raise ValidationError("A sold vehicle must have a tracking code.")

    if CarStageProgress.objects.filter(car=locked_car).exists():
        raise ValidationError("Tracking has already been started for this vehicle.")

    stages = list(Stage.objects.filter(is_active=True).order_by("order"))

    if not stages:
        raise ValidationError("At least one active tracking stage is required.")

    transition_map = _get_transition_map(stages)

    now = timezone.now()
    planned_date = now.date()

    progress_records = [
        CarStageProgress(
            car=locked_car,
            stage=stages[0],
            planned_date=planned_date,
            actual_arrival=now,
            confirmed_by=actor,
            completed_at=now,
            completed_by=actor,
        )
    ]

    for index in range(len(stages) - 1):
        transition = _get_required_transition(
            transition_map,
            stages[index],
            stages[index + 1],
        )

        planned_date += timedelta(days=transition.estimated_duration_days)

        progress_records.append(
            CarStageProgress(
                car=locked_car,
                stage=stages[index + 1],
                planned_date=planned_date,
            )
        )

    CarStageProgress.objects.bulk_create(progress_records)

    locked_car.current_stage = stages[0]
    locked_car.save(update_fields=["current_stage"])

    TrackingEvent.objects.create(
        car=locked_car,
        event_type=TrackingEvent.EventType.TRACKING_STARTED,
        previous_stage=None,
        new_stage=stages[0],
        performed_by=actor,
        source=source,
        note="Tracking started after vehicle sale confirmation.",
    )

    TrackingEvent.objects.create(
        car=locked_car,
        event_type=TrackingEvent.EventType.STAGE_COMPLETED,
        previous_stage=None,
        new_stage=stages[0],
        performed_by=actor,
        source=source,
        note="Sale Confirmed stage completed automatically.",
    )

    return locked_car


@transaction.atomic
def confirm_stage(
    *,
    car,
    stage,
    staff,
    source=TrackingEvent.Source.ADMIN_DASHBOARD,
):
    """
    Records that a vehicle has entered the next expected stage.
    """

    _validate_tracking_source(source)

    locked_car = car.__class__.objects.select_for_update().get(pk=car.pk)

    if not stage.is_active:
        raise ValidationError("An inactive stage cannot be entered.")

    _ensure_stage_confirmation_permission(
        actor=staff,
        stage=stage,
    )

    expected_stage = _get_next_expected_stage(locked_car)

    if expected_stage.pk != stage.pk:
        raise ValidationError(f"The next expected stage is '{expected_stage.name}'.")

    progress = CarStageProgress.objects.select_for_update().get(
        car=locked_car,
        stage=stage,
    )

    if progress.actual_arrival is not None:
        raise ValidationError("This stage has already been entered.")

    if progress.skipped_at is not None:
        raise ValidationError("A skipped stage cannot be entered.")

    previous_stage = locked_car.current_stage

    progress.actual_arrival = timezone.now()
    progress.confirmed_by = staff
    progress.save(
        update_fields=[
            "actual_arrival",
            "confirmed_by",
        ]
    )

    locked_car.current_stage = stage
    locked_car.save(update_fields=["current_stage"])

    TrackingEvent.objects.create(
        car=locked_car,
        event_type=TrackingEvent.EventType.STAGE_CONFIRMED,
        previous_stage=previous_stage,
        new_stage=stage,
        performed_by=staff,
        source=source,
        note="Vehicle entered this stage.",
    )

    return progress


@transaction.atomic
def complete_stage(
    *,
    car,
    stage,
    staff,
    source=TrackingEvent.Source.ADMIN_DASHBOARD,
):
    """
    Completes the vehicle's current entered stage.
    """

    _validate_tracking_source(source)

    if not stage.is_active:
        raise ValidationError("An inactive stage cannot be completed.")

    _ensure_stage_confirmation_permission(
        actor=staff,
        stage=stage,
    )

    locked_car = car.__class__.objects.select_for_update().get(pk=car.pk)

    if locked_car.current_stage is None:
        raise ValidationError("Tracking has not started for this vehicle.")

    if locked_car.current_stage_id != stage.pk:
        raise ValidationError("Only the current stage can be completed.")

    progress = CarStageProgress.objects.select_for_update().get(
        car=locked_car,
        stage=stage,
    )

    if progress.skipped_at is not None:
        raise ValidationError("A skipped stage cannot be completed.")

    if progress.actual_arrival is None:
        raise ValidationError("The vehicle has not entered this stage yet.")

    if progress.completed_at is not None:
        raise ValidationError("This stage has already been completed.")

    progress.completed_at = timezone.now()
    progress.completed_by = staff
    progress.save(
        update_fields=[
            "completed_at",
            "completed_by",
        ]
    )

    TrackingEvent.objects.create(
        car=locked_car,
        event_type=TrackingEvent.EventType.STAGE_COMPLETED,
        previous_stage=None,
        new_stage=stage,
        performed_by=staff,
        source=source,
        note="Stage completed.",
    )

    return progress


@transaction.atomic
def skip_stage(
    *,
    car,
    stage,
    actor,
    source=TrackingEvent.Source.ADMIN_DASHBOARD,
    note="",
):
    """
    Skips the next expected tracking stage.
    """

    _validate_tracking_source(source)

    require_permission(
        actor=actor,
        permission="tracking.skip_tracking_stage",
        error_message="شما اجازهٔ رد کردن مراحل رهگیری را ندارید.",
    )

    locked_car = car.__class__.objects.select_for_update().get(pk=car.pk)

    if not stage.is_active:
        raise ValidationError("An inactive stage cannot be skipped.")

    expected_stage = _get_next_expected_stage(locked_car)

    if expected_stage.pk != stage.pk:
        raise ValidationError(f"The next expected stage is '{expected_stage.name}'.")

    progress = CarStageProgress.objects.select_for_update().get(
        car=locked_car,
        stage=stage,
    )

    if progress.actual_arrival is not None:
        raise ValidationError("An entered stage cannot be skipped.")

    if progress.skipped_at is not None:
        raise ValidationError("This stage has already been skipped.")

    previous_stage = locked_car.current_stage

    progress.skipped_at = timezone.now()
    progress.skipped_by = actor
    progress.save(
        update_fields=[
            "skipped_at",
            "skipped_by",
        ]
    )

    locked_car.current_stage = stage
    locked_car.save(update_fields=["current_stage"])

    TrackingEvent.objects.create(
        car=locked_car,
        event_type=TrackingEvent.EventType.STAGE_SKIPPED,
        previous_stage=previous_stage,
        new_stage=stage,
        performed_by=actor,
        source=source,
        note=note or "Stage skipped by an authorized user.",
    )

    return progress


@transaction.atomic
def correct_tracking_stage(
    *,
    car,
    stage,
    actor,
    note,
    source=TrackingEvent.Source.ADMIN_DASHBOARD,
):
    """
    Moves a vehicle backward to an earlier stage.

    The target stage becomes entered again but not completed.
    Every later progress record returns to pending.
    Old TrackingEvent records are never changed.
    """

    _validate_tracking_source(source)

    if not note.strip():
        raise ValidationError("A correction note is required.")

    require_permission(
        actor=actor,
        permission="tracking.correct_tracking_stage",
        error_message="شما اجازهٔ اصلاح مراحل رهگیری را ندارید.",
    )

    locked_car = car.__class__.objects.select_for_update().get(pk=car.pk)

    if locked_car.current_stage is None:
        raise ValidationError("Tracking has not started for this vehicle.")

    if not stage.is_active:
        raise ValidationError("An inactive stage cannot be used for a correction.")

    if stage.order >= locked_car.current_stage.order:
        raise ValidationError("A correction must move the vehicle to an earlier stage.")

    target_progress = CarStageProgress.objects.select_for_update().get(
        car=locked_car,
        stage=stage,
    )

    later_progress_records = CarStageProgress.objects.select_for_update().filter(
        car=locked_car,
        stage__order__gt=stage.order,
    )

    for progress in later_progress_records:
        progress.actual_arrival = None
        progress.confirmed_by = None
        progress.completed_at = None
        progress.completed_by = None
        progress.skipped_at = None
        progress.skipped_by = None
        progress.save(
            update_fields=[
                "actual_arrival",
                "confirmed_by",
                "completed_at",
                "completed_by",
                "skipped_at",
                "skipped_by",
            ]
        )

    previous_stage = locked_car.current_stage

    target_progress.actual_arrival = timezone.now()
    target_progress.confirmed_by = actor
    target_progress.completed_at = None
    target_progress.completed_by = None
    target_progress.skipped_at = None
    target_progress.skipped_by = None
    target_progress.save(
        update_fields=[
            "actual_arrival",
            "confirmed_by",
            "completed_at",
            "completed_by",
            "skipped_at",
            "skipped_by",
        ]
    )

    locked_car.current_stage = stage
    locked_car.save(update_fields=["current_stage"])

    TrackingEvent.objects.create(
        car=locked_car,
        event_type=TrackingEvent.EventType.STAGE_CORRECTED,
        previous_stage=previous_stage,
        new_stage=stage,
        performed_by=actor,
        source=source,
        note=note.strip(),
    )

    return target_progress


def get_public_tracking_data(*, tracking_code):
    """
    Returns safe public tracking information for a vehicle.

    Customer identity, phone, Telegram ID, price, internal notes,
    and staff details are intentionally excluded.
    """

    normalized_code = tracking_code.strip()

    if not normalized_code:
        raise ValidationError("A tracking code is required.")

    progress_records = list(
        CarStageProgress.objects.select_related(
            "car",
            "stage",
        )
        .filter(car__tracking_code=normalized_code)
        .order_by("stage__order")
    )

    if not progress_records:
        raise ValidationError("No tracking record was found for this code.")

    car = progress_records[0].car

    if car.status not in [
        car.Status.SOLD,
        car.Status.IN_TRANSIT,
        car.Status.DELIVERED,
    ]:
        raise ValidationError("No tracking record was found for this code.")

    current_progress = next(
        (
            progress
            for progress in progress_records
            if progress.stage_id == car.current_stage_id
        ),
        None,
    )

    return {
        "tracking_code": car.tracking_code,
        "vehicle": {
            "title": car.title,
            "brand": car.brand,
            "model": car.model,
            "year": car.year,
            "color": car.color,
        },
        "status": car.status,
        "current_stage": (
            {
                "name": current_progress.stage.name,
                "order": current_progress.stage.order,
                "state": current_progress.state,
            }
            if current_progress
            else None
        ),
        "remaining_eta_days": calculate_remaining_eta_days(car),
        "stages": [
            {
                "name": progress.stage.name,
                "order": progress.stage.order,
                "state": progress.state,
                "planned_date": progress.planned_date,
                "actual_arrival": progress.actual_arrival,
                "completed_at": progress.completed_at,
                "skipped_at": progress.skipped_at,
            }
            for progress in progress_records
        ],
    }


def get_stage_archive_impact(*, stage):
    """
    Returns a read-only impact report before a stage is archived.

    The report separates active vehicles into categories so the
    Administrator can make an informed Yes / No decision.
    """

    if not stage.is_active:
        raise ValidationError("This stage is already archived.")

    progress_records = (
        CarStageProgress.objects.select_related(
            "car",
            "car__current_stage",
        )
        .filter(
            stage=stage,
            car__status__in=[
                "sold",
                "in_transit",
            ],
        )
        .order_by("car__tracking_code")
    )

    report = {
        "stage": {
            "id": stage.id,
            "name": stage.name,
            "order": stage.order,
        },
        "entered_not_completed": [],
        "completed_waiting_for_next": [],
        "not_reached": [],
        "already_passed": [],
    }

    for progress in progress_records:
        car = progress.car

        vehicle_data = {
            "car_id": car.id,
            "tracking_code": car.tracking_code,
            "title": car.title,
            "current_stage": (car.current_stage.name if car.current_stage else None),
            "current_stage_order": (
                car.current_stage.order if car.current_stage else None
            ),
        }

        if car.current_stage_id == stage.id:
            if progress.state == "entered":
                report["entered_not_completed"].append(vehicle_data)
            else:
                report["completed_waiting_for_next"].append(vehicle_data)

        elif car.current_stage and car.current_stage.order < stage.order:
            report["not_reached"].append(vehicle_data)

        elif car.current_stage and car.current_stage.order > stage.order:
            report["already_passed"].append(vehicle_data)

    report["counts"] = {
        "entered_not_completed": len(report["entered_not_completed"]),
        "completed_waiting_for_next": len(report["completed_waiting_for_next"]),
        "not_reached": len(report["not_reached"]),
        "already_passed": len(report["already_passed"]),
    }

    report["counts"]["total_affected"] = (
        report["counts"]["entered_not_completed"]
        + report["counts"]["completed_waiting_for_next"]
        + report["counts"]["not_reached"]
    )

    return report


@transaction.atomic
def archive_stage(
    *,
    stage,
    actor,
    replacement_duration_days,
    note,
    confirm_affected_vehicles=False,
    source=TrackingEvent.Source.ADMIN_DASHBOARD,
):
    """
    Archives a middle tracking stage safely.

    Vehicles currently inside the stage move back to the previous
    active stage. Vehicles that completed the stage move to the next
    active stage in Pending state. Vehicles that have not reached the
    stage receive a skipped progress record.
    """

    _validate_tracking_source(source)

    if not note.strip():
        raise ValidationError("An archive reason is required.")

    if replacement_duration_days is None:
        raise ValidationError("A replacement transition duration is required.")

    if replacement_duration_days < 0:
        raise ValidationError("Replacement transition duration cannot be negative.")

    require_permission(
        actor=actor,
        permission="tracking.archive_tracking_stage",
        error_message="شما اجازهٔ بایگانی کردن مراحل رهگیری را ندارید.",
    )

    if not confirm_affected_vehicles:
        raise ValidationError(
            "Explicit confirmation is required before archiving " "affected vehicles."
        )

    locked_stage = Stage.objects.select_for_update().get(pk=stage.pk)

    if not locked_stage.is_active:
        raise ValidationError("This stage is already archived.")

    previous_active_stage = (
        Stage.objects.filter(
            is_active=True,
            order__lt=locked_stage.order,
        )
        .order_by("-order")
        .first()
    )

    next_active_stage = (
        Stage.objects.filter(
            is_active=True,
            order__gt=locked_stage.order,
        )
        .order_by("order")
        .first()
    )

    if previous_active_stage is None or next_active_stage is None:
        raise ValidationError("The first or final active stage cannot be archived.")

    impact = get_stage_archive_impact(stage=locked_stage)

    StageTransition.objects.update_or_create(
        from_stage=previous_active_stage,
        to_stage=next_active_stage,
        defaults={
            "estimated_duration_days": replacement_duration_days,
            "is_active": True,
        },
    )

    StageTransition.objects.filter(
        from_stage=locked_stage,
    ).update(is_active=False)

    StageTransition.objects.filter(
        to_stage=locked_stage,
    ).update(is_active=False)

    affected_progress_records = list(
        CarStageProgress.objects.select_for_update()
        .select_related("car")
        .filter(
            stage=locked_stage,
            car__status__in=[
                "sold",
                "in_transit",
            ],
        )
        .order_by("car_id")
    )

    now = timezone.now()

    for original_progress in affected_progress_records:
        car = original_progress.car

        locked_car = car.__class__.objects.select_for_update().get(pk=car.pk)

        progress = CarStageProgress.objects.select_for_update().get(
            pk=original_progress.pk
        )

        if locked_car.current_stage_id == locked_stage.id:
            if progress.state == "entered":
                previous_progress = CarStageProgress.objects.select_for_update().get(
                    car=locked_car,
                    stage=previous_active_stage,
                )

                progress.actual_arrival = None
                progress.confirmed_by = None
                progress.completed_at = None
                progress.completed_by = None
                progress.skipped_at = now
                progress.skipped_by = actor
                progress.save(
                    update_fields=[
                        "actual_arrival",
                        "confirmed_by",
                        "completed_at",
                        "completed_by",
                        "skipped_at",
                        "skipped_by",
                    ]
                )

                previous_progress.actual_arrival = now
                previous_progress.confirmed_by = actor
                previous_progress.completed_at = None
                previous_progress.completed_by = None
                previous_progress.skipped_at = None
                previous_progress.skipped_by = None
                previous_progress.save(
                    update_fields=[
                        "actual_arrival",
                        "confirmed_by",
                        "completed_at",
                        "completed_by",
                        "skipped_at",
                        "skipped_by",
                    ]
                )

                locked_car.current_stage = previous_active_stage
                locked_car.save(update_fields=["current_stage"])

                TrackingEvent.objects.create(
                    car=locked_car,
                    event_type=TrackingEvent.EventType.STAGE_ARCHIVED,
                    previous_stage=locked_stage,
                    new_stage=previous_active_stage,
                    performed_by=actor,
                    source=source,
                    note=(
                        f"{note.strip()} Vehicle returned to the "
                        f"previous stage because the archived stage "
                        f"was entered but not completed."
                    ),
                )

            else:
                next_progress = CarStageProgress.objects.select_for_update().get(
                    car=locked_car,
                    stage=next_active_stage,
                )

                if next_progress.state != "pending":
                    raise ValidationError(
                        "The next active stage is not pending for "
                        f"vehicle '{locked_car}'."
                    )

                locked_car.current_stage = next_active_stage
                locked_car.save(update_fields=["current_stage"])

                TrackingEvent.objects.create(
                    car=locked_car,
                    event_type=TrackingEvent.EventType.STAGE_ARCHIVED,
                    previous_stage=locked_stage,
                    new_stage=next_active_stage,
                    performed_by=actor,
                    source=source,
                    note=(
                        f"{note.strip()} Vehicle moved to the next "
                        f"stage because the archived stage was "
                        f"already completed."
                    ),
                )

        elif (
            locked_car.current_stage
            and locked_car.current_stage.order < locked_stage.order
        ):
            if progress.state == "pending":
                progress.skipped_at = now
                progress.skipped_by = actor
                progress.save(
                    update_fields=[
                        "skipped_at",
                        "skipped_by",
                    ]
                )

                TrackingEvent.objects.create(
                    car=locked_car,
                    event_type=TrackingEvent.EventType.STAGE_ARCHIVED,
                    previous_stage=locked_car.current_stage,
                    new_stage=locked_stage,
                    performed_by=actor,
                    source=source,
                    note=(
                        f"{note.strip()} Archived stage was skipped "
                        f"before the vehicle reached it."
                    ),
                )

    locked_stage.is_active = False
    locked_stage.save(update_fields=["is_active"])

    return {
        "archived_stage": {
            "id": locked_stage.id,
            "name": locked_stage.name,
        },
        "replacement_transition": {
            "from_stage": previous_active_stage.name,
            "to_stage": next_active_stage.name,
            "estimated_duration_days": replacement_duration_days,
        },
        "impact": impact,
    }
