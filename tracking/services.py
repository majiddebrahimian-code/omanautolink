from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from accounts.authorization import (
    require_active_internal_staff,
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


def _create_tracking_event(**event_data):
    """
    Persists one immutable tracking event and explicitly requests customer notices.

    Keeping this side effect here makes every workflow path (web admin, bot,
    import, correction, and stage archive) use the same transactional rule.
    No external network call is made here; only durable Outbox work is created.
    """

    tracking_event = TrackingEvent.objects.create(**event_data)

    # A local import keeps the domain model independent during Django startup.
    from integrations.services import queue_customer_tracking_notifications_for_event

    queue_customer_tracking_notifications_for_event(
        tracking_event=tracking_event,
    )

    return tracking_event


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


def _sync_car_tracking_status(*, locked_car):
    """Synchronize the denormalized car status with durable stage progress.

    ``Car.status`` is used for efficient internal lists, while
    ``CarStageProgress`` remains the detailed source of workflow history.  The
    synchronization is deliberately kept in this shared service module so a
    website form, Telegram handler, and Excel import cannot disagree about
    whether a vehicle is sold, in transit, or delivered.

    The automatically completed first stage means only "sale confirmed".
    Therefore a vehicle stays ``sold`` until it reaches a later operational
    stage.  Completing or skipping the final active stage marks it delivered.
    """

    if locked_car.status not in {
        locked_car.Status.SOLD,
        locked_car.Status.IN_TRANSIT,
        locked_car.Status.DELIVERED,
    }:
        return locked_car

    if locked_car.current_stage_id is None:
        return locked_car

    active_stages = list(Stage.objects.filter(is_active=True).order_by("order"))

    if not active_stages:
        return locked_car

    first_active_stage = active_stages[0]
    final_active_stage = active_stages[-1]
    final_progress = CarStageProgress.objects.filter(
        car=locked_car,
        stage=final_active_stage,
    ).first()

    if final_progress and final_progress.state in {"completed", "skipped"}:
        target_status = locked_car.Status.DELIVERED
    elif locked_car.current_stage_id == first_active_stage.id:
        target_status = locked_car.Status.SOLD
    else:
        target_status = locked_car.Status.IN_TRANSIT

    if locked_car.status != target_status:
        locked_car.status = target_status
        locked_car.save(update_fields=["status"])

    return locked_car


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


def _require_system_administrator(*, actor):
    """Keep delivery-route administration inside the shared domain layer.

    The custom panel is not the only future caller of these functions: a
    management API or an audited administrative bot command must be governed
    by exactly the same rule.  A stage definition affects every active
    shipment, so an ordinary employee is deliberately not enough here.
    """

    require_active_internal_staff(actor=actor)

    if not actor.is_superuser:
        raise ValidationError(
            "فقط مدیر سیستم می‌تواند ساختار مراحل تحویل را تغییر دهد."
        )


def _get_active_stage_chain(*, lock=False):
    """Return the one ordered active route and reject ambiguous legacy data."""

    queryset = Stage.objects.filter(is_active=True).order_by("order", "pk")

    if lock:
        queryset = queryset.select_for_update()

    stages = list(queryset)
    orders = [stage.order for stage in stages]

    if len(orders) != len(set(orders)):
        raise ValidationError(
            "ترتیب مراحل فعال یکتا نیست؛ ابتدا دادهٔ مراحل را توسط مدیر سیستم اصلاح کنید."
        )

    return stages


def _get_linear_transition_map(*, stages, lock=False):
    """Validate and return the transitions of a strictly linear route.

    ``StageTransition`` can technically hold any forward relation, while the
    business workflow is intentionally linear.  Management operations must
    therefore fail safely when a manually-created branch is present rather
    than silently calculating an incorrect ETA.
    """

    if len(stages) < 2:
        return {}

    queryset = StageTransition.objects.filter(
        is_active=True,
        from_stage__in=stages,
        to_stage__in=stages,
    )

    if lock:
        queryset = queryset.select_for_update()

    transitions = list(queryset)
    transition_map = {
        (transition.from_stage_id, transition.to_stage_id): transition
        for transition in transitions
    }
    expected_pairs = {
        (stages[index].pk, stages[index + 1].pk)
        for index in range(len(stages) - 1)
    }

    if set(transition_map) != expected_pairs:
        raise ValidationError(
            "مسیر مراحل فعال خطی و کامل نیست؛ ابتدا Transitionهای مراحل را اصلاح کنید."
        )

    return transition_map


def get_linear_stage_route_integrity():
    """Describe the active route without raising for missing legacy links.

    Older installations can contain valid Stage rows created before the custom
    stage-management panel existed, but no StageTransition rows between them.
    The public result lets the backoffice show a repair workflow instead of
    trapping an administrator in a validation-error loop.
    """

    stages = _get_active_stage_chain()
    all_transitions = list(
        StageTransition.objects.filter(
            from_stage__in=stages,
            to_stage__in=stages,
        ).select_related("from_stage", "to_stage")
    )
    active_transition_map = {
        (transition.from_stage_id, transition.to_stage_id): transition
        for transition in all_transitions
        if transition.is_active
    }
    transition_by_pair = {
        (transition.from_stage_id, transition.to_stage_id): transition
        for transition in all_transitions
    }
    expected_pairs = [
        (stages[index], stages[index + 1])
        for index in range(len(stages) - 1)
    ]
    expected_pair_ids = {
        (from_stage.pk, to_stage.pk)
        for from_stage, to_stage in expected_pairs
    }
    unexpected_transitions = [
        transition
        for pair, transition in active_transition_map.items()
        if pair not in expected_pair_ids
    ]
    pairs = [
        {
            "from_stage": from_stage,
            "to_stage": to_stage,
            "transition": active_transition_map.get(
                (from_stage.pk, to_stage.pk)
            ),
            "stored_transition": transition_by_pair.get(
                (from_stage.pk, to_stage.pk)
            ),
        }
        for from_stage, to_stage in expected_pairs
    ]

    return {
        "stages": stages,
        "pairs": pairs,
        "missing_pairs": [
            pair for pair in pairs if pair["transition"] is None
        ],
        "unexpected_transitions": unexpected_transitions,
        "is_valid": not any(
            pair["transition"] is None for pair in pairs
        ) and not unexpected_transitions,
    }


@transaction.atomic
def repair_linear_stage_transitions(*, actor, transition_durations):
    """Safely create or reactivate the exact links of the active linear route.

    The business workflow is explicitly linear.  During this administrator-
    confirmed repair, active branches outside the consecutive route are
    soft-disabled (never deleted), then every required pair is created or
    reactivated.  Pending ETA values for in-flight vehicles are recalculated
    atomically; actual operational history is never rewritten.
    """

    _require_system_administrator(actor=actor)
    active_stages = _get_active_stage_chain(lock=True)

    if len(active_stages) < 2:
        raise ValidationError(
            "برای تعریف Transition دست‌کم دو مرحلهٔ فعال لازم است."
        )

    expected_pairs = [
        (active_stages[index], active_stages[index + 1])
        for index in range(len(active_stages) - 1)
    ]
    expected_pair_ids = {
        (from_stage.pk, to_stage.pk)
        for from_stage, to_stage in expected_pairs
    }
    stored_transitions = list(
        StageTransition.objects.select_for_update()
        .filter(
            from_stage__in=active_stages,
            to_stage__in=active_stages,
        )
        .select_related("from_stage", "to_stage")
    )
    active_unexpected_transitions = [
        transition
        for transition in stored_transitions
        if transition.is_active
        and (transition.from_stage_id, transition.to_stage_id)
        not in expected_pair_ids
    ]

    deactivated_count = 0
    for transition in active_unexpected_transitions:
        transition.is_active = False
        transition.save(update_fields=["is_active"])
        deactivated_count += 1

    transition_by_pair = {
        (transition.from_stage_id, transition.to_stage_id): transition
        for transition in stored_transitions
    }
    transition_map = {}
    created_count = 0
    reactivated_count = 0
    updated_count = 0

    for from_stage, to_stage in expected_pairs:
        pair = (from_stage.pk, to_stage.pk)
        try:
            raw_duration = transition_durations[pair]
        except (KeyError, TypeError) as error:
            raise ValidationError(
                f"مدت انتقال از «{from_stage.name}» به «{to_stage.name}» الزامی است."
            ) from error

        duration = _normalize_duration_days(raw_duration, required=True)
        transition = transition_by_pair.get(pair)

        if transition is None:
            transition = StageTransition.objects.create(
                from_stage=from_stage,
                to_stage=to_stage,
                estimated_duration_days=duration,
                is_active=True,
            )
            created_count += 1
        else:
            changed_fields = []
            if not transition.is_active:
                transition.is_active = True
                changed_fields.append("is_active")
                reactivated_count += 1
            if transition.estimated_duration_days != duration:
                transition.estimated_duration_days = duration
                changed_fields.append("estimated_duration_days")
                updated_count += 1
            if changed_fields:
                transition.save(update_fields=changed_fields)

        if to_stage.default_duration_days != duration:
            to_stage.default_duration_days = duration
            to_stage.save(update_fields=["default_duration_days"])

        transition_map[pair] = transition

    replanned_vehicle_count = _replan_in_flight_vehicles(
        stages=active_stages,
        transition_map=transition_map,
    )

    return {
        "stages": active_stages,
        "created_count": created_count,
        "reactivated_count": reactivated_count,
        "updated_count": updated_count,
        "deactivated_count": deactivated_count,
        "replanned_vehicle_count": replanned_vehicle_count,
    }


def _normalize_stage_name(name):
    normalized_name = str(name or "").strip()

    if not normalized_name:
        raise ValidationError("نام مرحله الزامی است.")

    if len(normalized_name) > 120:
        raise ValidationError("نام مرحله نمی‌تواند بیشتر از ۱۲۰ کاراکتر باشد.")

    return normalized_name


def _normalize_duration_days(duration_days, *, required):
    if duration_days in (None, ""):
        if required:
            raise ValidationError("مدت زمان انتقال بین مراحل الزامی است.")
        return 0

    if isinstance(duration_days, bool):
        raise ValidationError("مدت زمان انتقال معتبر نیست.")

    try:
        normalized_duration = int(duration_days)
    except (TypeError, ValueError):
        raise ValidationError("مدت زمان انتقال باید یک عدد صحیح باشد.")

    if normalized_duration < 0:
        raise ValidationError("مدت زمان انتقال نمی‌تواند منفی باشد.")

    return normalized_duration


def _get_validated_stage_staff_profiles(assigned_staff):
    """Resolve staff selections and keep invalid assignees out of a stage."""

    from accounts.models import StaffProfile

    profile_ids = {
        profile.pk
        for profile in (assigned_staff or [])
        if getattr(profile, "pk", None) is not None
    }

    profiles = list(
        StaffProfile.objects.select_related("user")
        .filter(pk__in=profile_ids)
        .order_by("user__first_name", "user__last_name", "user__username")
    )

    if len(profiles) != len(profile_ids):
        raise ValidationError("یکی از کارمندان انتخاب‌شده معتبر نیست.")

    for profile in profiles:
        user = profile.user

        if not user.is_active or not user.is_staff:
            raise ValidationError(
                "فقط کاربران داخلی و فعال می‌توانند مسئول یک مرحله باشند."
            )

        if not user.is_superuser and not user.has_perm(
            "tracking.confirm_tracking_stage"
        ):
            raise ValidationError(
                "کارمند انتخاب‌شده مجوز تأیید مرحلهٔ رهگیری را ندارد."
            )

    return profiles


def _recalculate_pending_planned_dates(*, car, stages, transition_map):
    """Re-plan only future, pending records after an ETA configuration change.

    Actual arrival/completion timestamps are immutable operational history.  A
    dynamic ETA must update the remaining plan without rewriting that history.
    """

    progress_by_stage_id = {
        progress.stage_id: progress
        for progress in CarStageProgress.objects.select_for_update()
        .filter(car=car, stage__in=stages)
        .select_related("stage")
    }

    if not stages:
        return

    first_progress = progress_by_stage_id.get(stages[0].pk)
    planned_date = (
        first_progress.planned_date
        if first_progress and first_progress.planned_date
        else car.created_at.date()
    )

    for index, stage in enumerate(stages):
        if index:
            transition = transition_map[(stages[index - 1].pk, stage.pk)]
            planned_date += timedelta(days=transition.estimated_duration_days)

        progress = progress_by_stage_id.get(stage.pk)

        if progress and progress.state == "pending" and progress.planned_date != planned_date:
            progress.planned_date = planned_date
            progress.save(update_fields=["planned_date"])


def _replan_in_flight_vehicles(*, stages, transition_map, new_stage=None):
    """Backfill a newly appended stage and refresh dynamic future schedules."""

    from cars.models import Car

    updated_vehicle_count = 0
    in_flight_cars = Car.objects.select_for_update().filter(
        is_deleted=False,
        status__in=[Car.Status.SOLD, Car.Status.IN_TRANSIT],
    )

    for car in in_flight_cars.order_by("pk"):
        if new_stage is not None:
            CarStageProgress.objects.get_or_create(
                car=car,
                stage=new_stage,
            )

        _recalculate_pending_planned_dates(
            car=car,
            stages=stages,
            transition_map=transition_map,
        )
        updated_vehicle_count += 1

    return updated_vehicle_count


@transaction.atomic
def create_linear_stage(
    *,
    actor,
    name,
    duration_from_previous=None,
    assigned_staff=(),
):
    """Append one stage to the active linear route through shared logic.

    Adding a stage in the middle of an active route or reordering stages has
    material effects on vehicles that are already in transit.  Those operations
    intentionally require a future preview-and-confirm workflow.  This safe
    first operation appends the stage, creates its incoming transition and
    backfills pending ``CarStageProgress`` records transactionally.
    """

    _require_system_administrator(actor=actor)
    normalized_name = _normalize_stage_name(name)
    normalized_staff_profiles = _get_validated_stage_staff_profiles(assigned_staff)

    all_stages = list(Stage.objects.select_for_update().order_by("order", "pk"))
    active_stages = [stage for stage in all_stages if stage.is_active]

    if any(stage.name.casefold() == normalized_name.casefold() for stage in active_stages):
        raise ValidationError("یک مرحلهٔ فعال با این نام از قبل وجود دارد.")

    transition_map = _get_linear_transition_map(stages=active_stages, lock=True)
    previous_stage = active_stages[-1] if active_stages else None
    normalized_duration = _normalize_duration_days(
        duration_from_previous,
        required=previous_stage is not None,
    )

    stage = Stage.objects.create(
        name=normalized_name,
        order=max((existing_stage.order for existing_stage in all_stages), default=0)
        + 1,
        default_duration_days=normalized_duration,
        is_active=True,
    )

    if previous_stage is not None:
        transition = StageTransition.objects.create(
            from_stage=previous_stage,
            to_stage=stage,
            estimated_duration_days=normalized_duration,
            is_active=True,
        )
        transition_map[(previous_stage.pk, stage.pk)] = transition

    stage.staff_members.set(normalized_staff_profiles)
    _replan_in_flight_vehicles(
        stages=[*active_stages, stage],
        transition_map=transition_map,
        new_stage=stage,
    )

    return stage


@transaction.atomic
def update_linear_stage(
    *,
    stage,
    actor,
    name,
    duration_from_previous=None,
    assigned_staff=(),
):
    """Safely edit a stage label, its incoming ETA and its responsible staff."""

    _require_system_administrator(actor=actor)
    normalized_name = _normalize_stage_name(name)
    normalized_staff_profiles = _get_validated_stage_staff_profiles(assigned_staff)

    active_stages = _get_active_stage_chain(lock=True)
    stage_by_id = {active_stage.pk: active_stage for active_stage in active_stages}
    locked_stage = stage_by_id.get(stage.pk)

    if locked_stage is None:
        raise ValidationError("فقط مرحله‌های فعال قابل ویرایش هستند.")

    if any(
        active_stage.pk != locked_stage.pk
        and active_stage.name.casefold() == normalized_name.casefold()
        for active_stage in active_stages
    ):
        raise ValidationError("یک مرحلهٔ فعال با این نام از قبل وجود دارد.")

    transition_map = _get_linear_transition_map(stages=active_stages, lock=True)
    stage_index = active_stages.index(locked_stage)
    previous_stage = active_stages[stage_index - 1] if stage_index else None
    changed_fields = []

    if locked_stage.name != normalized_name:
        locked_stage.name = normalized_name
        changed_fields.append("name")

    if previous_stage is not None:
        normalized_duration = _normalize_duration_days(
            duration_from_previous,
            required=True,
        )
        transition = transition_map[(previous_stage.pk, locked_stage.pk)]

        if transition.estimated_duration_days != normalized_duration:
            transition.estimated_duration_days = normalized_duration
            transition.save(update_fields=["estimated_duration_days"])

        if locked_stage.default_duration_days != normalized_duration:
            locked_stage.default_duration_days = normalized_duration
            changed_fields.append("default_duration_days")

    if changed_fields:
        locked_stage.save(update_fields=changed_fields)

    locked_stage.staff_members.set(normalized_staff_profiles)
    _replan_in_flight_vehicles(
        stages=active_stages,
        transition_map=transition_map,
    )

    return locked_stage


def _get_progress_handler(progress):
    """Return the employee who actually last handled one progress record."""

    if progress is None:
        return None

    if progress.state == "entered":
        return progress.confirmed_by

    if progress.state == "completed":
        return progress.completed_by or progress.confirmed_by

    if progress.state == "skipped":
        return progress.skipped_by or progress.confirmed_by

    return None


def _get_next_active_stage(*, stage, active_stages):
    if stage is None:
        return None

    for active_stage in active_stages:
        if active_stage.order > stage.order:
            return active_stage

    return None


def get_delivery_machine_snapshot(*, car_id):
    """Return one read-only operational delivery dossier for the panel.

    It distinguishes the workflow cursor from physical location.  For example,
    after a stage is completed the car still points at that stage until the
    next stage confirms arrival; the responsible staff shown in the dossier is
    then the staff of the *next* stage and the previous handler remains visible
    as the last employee involved.
    """

    from accounts.models import StaffProfile
    from cars.models import Car, CarPhoto

    progress_queryset = CarStageProgress.objects.select_related(
        "stage",
        "confirmed_by",
        "completed_by",
        "skipped_by",
    ).order_by("stage__order", "stage__pk")
    event_queryset = TrackingEvent.objects.select_related(
        "previous_stage",
        "new_stage",
        "performed_by",
    ).order_by("-created_at", "-pk")
    photo_queryset = (
        CarPhoto.objects.filter(image__isnull=False)
        .exclude(image="")
        .order_by("-is_cover", "sort_order", "pk")
    )

    car = Car.objects.select_related("customer", "current_stage").prefetch_related(
        Prefetch("photos", queryset=photo_queryset, to_attr="delivery_photos"),
        Prefetch(
            "stage_progress",
            queryset=progress_queryset,
            to_attr="delivery_progress_records",
        ),
        Prefetch(
            "tracking_events",
            queryset=event_queryset,
            to_attr="delivery_tracking_events",
        ),
    ).get(
        pk=car_id,
        is_deleted=False,
        status__in=[Car.Status.SOLD, Car.Status.IN_TRANSIT, Car.Status.DELIVERED],
    )

    active_stages = list(
        Stage.objects.filter(is_active=True)
        .order_by("order", "pk")
        .prefetch_related(
            Prefetch(
                "staff_members",
                queryset=StaffProfile.objects.select_related("user").filter(
                    user__is_active=True,
                    user__is_staff=True,
                ),
                to_attr="delivery_staff_profiles",
            )
        )
    )
    active_stage_by_id = {stage.pk: stage for stage in active_stages}
    progress_records = list(car.delivery_progress_records)
    progress_by_stage_id = {
        progress.stage_id: progress for progress in progress_records
    }
    events = list(car.delivery_tracking_events)
    latest_event = events[0] if events else None
    current_stage = car.current_stage
    current_progress = progress_by_stage_id.get(car.current_stage_id)
    state = current_progress.state if current_progress else "unknown"
    next_active_stage = _get_next_active_stage(
        stage=current_stage,
        active_stages=active_stages,
    )

    def stage_staff(stage):
        if stage is None:
            return []
        return list(getattr(stage, "delivery_staff_profiles", []))

    last_handler = _get_progress_handler(current_progress)
    if last_handler is None:
        for progress in reversed(progress_records):
            last_handler = _get_progress_handler(progress)
            if last_handler is not None:
                break

    if last_handler is None and latest_event is not None:
        last_handler = latest_event.performed_by

    if current_stage is None:
        workflow = {
            "tone": "warning",
            "title": "رهگیری هنوز شروع نشده یا دادهٔ آن ناقص است",
            "description": "برای این ماشین مرحلهٔ فعلی قابل تشخیص نیست.",
            "responsible_stage": None,
            "responsible_staff": [],
            
            "last_handler": last_handler,
        }
    elif current_progress is None:
        workflow = {
            "tone": "warning",
            "title": "رکورد مرحلهٔ فعلی ناقص است",
            "description": (
                f"برای مرحلهٔ «{current_stage.name}» رکورد پیشرفت پیدا نشد. "
                "دادهٔ رهگیری باید بررسی شود."
            ),
            "responsible_stage": active_stage_by_id.get(current_stage.pk),
            "responsible_staff": stage_staff(
                active_stage_by_id.get(current_stage.pk)
            ),
            "last_handler": last_handler,
        }
    elif state == "entered":
        responsible_stage = active_stage_by_id.get(current_stage.pk, current_stage)
        workflow = {
            "tone": "active",
            "title": f"ماشین وارد مرحلهٔ «{current_stage.name}» شده است",
            "description": "مرحله هنوز تکمیل نشده و مسئولان همین مرحله پیگیری می‌کنند.",
            "responsible_stage": responsible_stage,
            "responsible_staff": stage_staff(responsible_stage),
            "last_handler": current_progress.confirmed_by or last_handler,
        }
    elif state in {"completed", "skipped"} and next_active_stage is not None:
        action_label = "کامل شده" if state == "completed" else "رد شده"
        workflow = {
            "tone": "waiting",
            "title": (
                f"مرحلهٔ «{current_stage.name}» {action_label}؛ "
                f"ماشین منتظر دریافت در «{next_active_stage.name}» است"
            ),
            "description": (
                "هنوز ورود ماشین به مرحلهٔ بعد توسط کارمند آن مرحله تأیید نشده است."
            ),
            "responsible_stage": next_active_stage,
            "responsible_staff": stage_staff(next_active_stage),
            "last_handler": _get_progress_handler(current_progress) or last_handler,
        }
    elif state == "pending":
        responsible_stage = active_stage_by_id.get(current_stage.pk, current_stage)
        workflow = {
            "tone": "waiting",
            "title": f"ماشین منتظر دریافت در مرحلهٔ «{current_stage.name}» است",
            "description": (
                "این حالت می‌تواند پس از اصلاح یا بایگانی یک مرحله رخ دهد؛ "
                "کارمند مسئول باید ورود ماشین را تأیید کند."
            ),
            "responsible_stage": responsible_stage,
            "responsible_staff": stage_staff(responsible_stage),
            "last_handler": last_handler,
        }
    else:
        workflow = {
            "tone": "complete",
            "title": "تمام مراحل فعال تحویل کامل شده‌اند",
            "description": "فرآیند رهگیری این ماشین به پایان رسیده است.",
            "responsible_stage": None,
            "responsible_staff": [],
            
            "last_handler": _get_progress_handler(current_progress) or last_handler,
        }

    try:
        remaining_eta_days = (
            calculate_remaining_eta_days(car)
            if car.current_stage_id in active_stage_by_id
            else None
        )
        eta_is_available = remaining_eta_days is not None
    except ValidationError:
        remaining_eta_days = None
        eta_is_available = False

    state_labels = {
        "pending": "در انتظار دریافت",
        "entered": "وارد مرحله شده",
        "completed": "تکمیل شده",
        "skipped": "رد شده",
    }
    event_labels = {
        TrackingEvent.EventType.TRACKING_STARTED: "شروع رهگیری",
        TrackingEvent.EventType.STAGE_CONFIRMED: "تأیید ورود به مرحله",
        TrackingEvent.EventType.STAGE_COMPLETED: "تکمیل مرحله",
        TrackingEvent.EventType.STAGE_CORRECTED: "اصلاح مرحله",
        TrackingEvent.EventType.STAGE_SKIPPED: "رد کردن مرحله",
        TrackingEvent.EventType.STAGE_ARCHIVED: "بایگانی مرحله",
    }
    source_labels = {
        TrackingEvent.Source.SYSTEM: "سیستم",
        TrackingEvent.Source.ADMIN_DASHBOARD: "پنل مدیریت",
        TrackingEvent.Source.TELEGRAM_BOT: "ربات تلگرام",
        TrackingEvent.Source.EXCEL_IMPORT: "فایل Excel",
    }

    return {
        "car": car,
        "cover_photo": next(iter(car.delivery_photos), None),
        "progress_records": progress_records,
        "timeline": [
            {
                "progress": progress,
                "state": progress.state,
                "state_label": state_labels.get(progress.state, "نامشخص"),
            }
            for progress in progress_records
        ],
        "events": [
            {
                "event": event,
                "event_label": event_labels.get(event.event_type, event.event_type),
                "source_label": source_labels.get(event.source, event.source),
            }
            for event in events
        ],
        "current_stage": current_stage,
        "current_progress": current_progress,
        "next_active_stage": next_active_stage,
        "workflow": workflow,
        "latest_event": latest_event,
        "latest_event_source_label": (
            source_labels.get(latest_event.source, latest_event.source)
            if latest_event is not None
            else None
        ),
        "remaining_eta_days": remaining_eta_days,
        "eta_is_available": eta_is_available,
        "tracking_code_is_missing": not bool(car.tracking_code),
    }


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

    stages = _get_active_stage_chain()

    if not stages:
        raise ValidationError("At least one active tracking stage is required.")

    transition_map = _get_linear_transition_map(stages=stages)

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

    _create_tracking_event(
        car=locked_car,
        event_type=TrackingEvent.EventType.TRACKING_STARTED,
        previous_stage=None,
        new_stage=stages[0],
        performed_by=actor,
        source=source,
        note="Tracking started after vehicle sale confirmation.",
    )

    _create_tracking_event(
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

    _sync_car_tracking_status(locked_car=locked_car)

    _create_tracking_event(
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

    _sync_car_tracking_status(locked_car=locked_car)

    _create_tracking_event(
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

    _sync_car_tracking_status(locked_car=locked_car)

    _create_tracking_event(
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

    _sync_car_tracking_status(locked_car=locked_car)

    _create_tracking_event(
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

                _sync_car_tracking_status(locked_car=locked_car)

                _create_tracking_event(
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

                _sync_car_tracking_status(locked_car=locked_car)

                _create_tracking_event(
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

                _create_tracking_event(
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
