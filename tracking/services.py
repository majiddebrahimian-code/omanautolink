from datetime import timedelta

from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CarStageProgress, Stage, StageTransition


def create_progress_for_car(car):
    """
    وقتی خودرو وارد سیستم می‌شود، برای هر استیج فعال یک رکورد پیشرفت
    با تاریخ پیش‌بینی‌شده (مرحله‌ای) می‌سازد.
    """
    stages = Stage.objects.filter(is_active=True).order_by("order")

    planned = timezone.now().date()
    records = []
    for stage in stages:
        planned = planned + timedelta(days=stage.default_duration_days)
        records.append(CarStageProgress(car=car, stage=stage, planned_date=planned))

    CarStageProgress.objects.bulk_create(records)
    return records


@transaction.atomic
def confirm_stage(car, stage, staff):
    """
    رسیدن خودرو به یک استیج را تأیید می‌کند، با رعایت قانون خطی:
    یک استیج تنها وقتی تأیید می‌شود که استیج قبلی تأیید شده باشد.
    """
    previous = (
        Stage.objects.filter(is_active=True, order__lt=stage.order)
        .order_by("-order")
        .first()
    )

    if previous:
        prev_progress = CarStageProgress.objects.get(car=car, stage=previous)
        if prev_progress.actual_arrival is None:
            raise ValidationError(f"ابتدا باید استیج «{previous.name}» تأیید شود.")

    progress = CarStageProgress.objects.get(car=car, stage=stage)
    progress.actual_arrival = timezone.now()
    progress.confirmed_by = staff
    progress.save()

    car.current_stage = stage
    car.save()

    return progress


def get_delay_days(progress):
    """
    اختلاف تاریخ واقعی و پیش‌بینی‌شده را برمی‌گرداند.
    مثبت = عقب‌تر از برنامه، منفی = جلوتر از برنامه، None = هنوز نرسیده.
    """
    if progress.actual_arrival is None or progress.planned_date is None:
        return None
    actual_date = progress.actual_arrival.date()
    return (actual_date - progress.planned_date).days


def calculate_remaining_eta_days(car):
    """
    Calculates the dynamic estimated number of remaining delivery days.

    The calculation starts from the car's current stage and sums the
    duration of all remaining active stage transitions.
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

    transitions = StageTransition.objects.filter(
        is_active=True,
        from_stage__in=stages,
        to_stage__in=stages,
    )

    transition_map = {
        (transition.from_stage_id, transition.to_stage_id): transition
        for transition in transitions
    }

    total_days = 0

    for index in range(len(stages) - 1):
        from_stage = stages[index]
        to_stage = stages[index + 1]

        transition = transition_map.get((from_stage.id, to_stage.id))

        if transition is None:
            raise ValidationError(
                f"No active transition is configured from "
                f"'{from_stage.name}' to '{to_stage.name}'."
            )

        total_days += transition.estimated_duration_days

    return total_days
