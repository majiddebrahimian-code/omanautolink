"""Shared technical validation and public payloads for vehicle 360° media.

This module intentionally validates only facts the system can verify: file
availability, sequence order, dimensions, and aspect-ratio consistency.  It
does not claim to recognise a vehicle or prove that staff photographed every
physical angle; that remains a human capture/review responsibility.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Car


MINIMUM_SPIN_FRAME_COUNT = 12
RECOMMENDED_SPIN_FRAME_COUNT = 24
MINIMUM_SPIN_FRAME_WIDTH = 320
MINIMUM_SPIN_FRAME_HEIGHT = 180
MAXIMUM_ASPECT_RATIO_DIFFERENCE = 0.035


@dataclass(frozen=True)
class SpinReadiness:
    is_ready: bool
    frame_count: int
    is_recommended: bool
    messages: tuple[str, ...]


def assess_car_spin_frames(car):
    """Return a deterministic, non-destructive technical readiness result."""

    frames = list(car.spin_frames.order_by("sequence", "pk"))
    messages = []

    if len(frames) < MINIMUM_SPIN_FRAME_COUNT:
        messages.append(
            f"حداقل {MINIMUM_SPIN_FRAME_COUNT} فریم برای نمایش ۳۶۰ لازم است."
        )

    expected_sequences = list(range(1, len(frames) + 1))
    actual_sequences = [frame.sequence for frame in frames]
    if actual_sequences != expected_sequences:
        messages.append("شمارهٔ فریم‌ها باید بدون فاصله و از ۱ شروع شود.")

    dimensions = []
    for frame in frames:
        if not frame.image:
            messages.append(f"فریم {frame.sequence} تصویر ندارد.")
            continue

        width = frame.image_width
        height = frame.image_height
        if not width or not height:
            messages.append(f"ابعاد فریم {frame.sequence} قابل‌خواندن نیست.")
            continue

        if width < MINIMUM_SPIN_FRAME_WIDTH or height < MINIMUM_SPIN_FRAME_HEIGHT:
            messages.append(
                f"ابعاد فریم {frame.sequence} برای نمایش ۳۶۰ بسیار کوچک است."
            )
            continue

        dimensions.append((frame.sequence, width, height))

    if dimensions:
        reference_ratio = dimensions[0][1] / dimensions[0][2]
        for sequence, width, height in dimensions[1:]:
            ratio = width / height
            if abs((ratio / reference_ratio) - 1) > MAXIMUM_ASPECT_RATIO_DIFFERENCE:
                messages.append(
                    f"نسبت تصویر فریم {sequence} با سایر فریم‌ها یکسان نیست."
                )

    return SpinReadiness(
        is_ready=not messages,
        frame_count=len(frames),
        is_recommended=len(frames) >= RECOMMENDED_SPIN_FRAME_COUNT,
        messages=tuple(messages),
    )


def get_public_spin_payload(car):
    """Return ordered, safe client data only for an approved ready viewer."""

    if not car or not car.spin_360_enabled:
        return None

    readiness = assess_car_spin_frames(car)
    if not readiness.is_ready:
        return None

    frame_urls = [
        frame.image.url
        for frame in car.spin_frames.order_by("sequence", "pk")
        if frame.image
    ]
    if len(frame_urls) != readiness.frame_count:
        return None

    return {
        "frame_urls": frame_urls,
        "frame_count": readiness.frame_count,
        "is_recommended": readiness.is_recommended,
    }


@transaction.atomic
def enable_car_spin_360(*, car_id, actor):
    """Explicitly approve an already technically-ready spin sequence."""

    if not (
        actor.is_active
        and (actor.is_superuser or actor.has_perm("cars.change_car"))
    ):
        raise ValidationError("اجازهٔ فعال‌سازی نمایش ۳۶۰ این خودرو را ندارید.")

    car = Car.objects.select_for_update().get(pk=car_id)
    readiness = assess_car_spin_frames(car)
    if not readiness.is_ready:
        raise ValidationError(list(readiness.messages))

    car.spin_360_enabled = True
    car.save(update_fields=["spin_360_enabled", "updated_at"])
    return car


@transaction.atomic
def disable_car_spin_360(*, car_id, actor):
    """Disable public interaction without deleting staff-uploaded frame media."""

    if not (
        actor.is_active
        and (actor.is_superuser or actor.has_perm("cars.change_car"))
    ):
        raise ValidationError("اجازهٔ غیرفعال‌سازی نمایش ۳۶۰ این خودرو را ندارید.")

    car = Car.objects.select_for_update().get(pk=car_id)
    car.spin_360_enabled = False
    car.save(update_fields=["spin_360_enabled", "updated_at"])
    return car
