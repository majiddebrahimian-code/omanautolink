from datetime import timedelta

from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Stage, CarStageProgress


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
