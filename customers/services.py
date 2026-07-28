from django.core.exceptions import ValidationError

from cars.models import Car

from .models import SearchLog


def record_successful_tracking_lookup(
    *,
    tracking_code,
    source,
    user_agent="",
):
    """
    Records one successful public tracking lookup.

    This function is shared by Website and Telegram Bot adapters.
    It does not calculate tracking data; it only stores audit data.
    """

    normalized_code = tracking_code.strip()

    if source not in SearchLog.Source.values:
        raise ValidationError("Invalid tracking lookup source.")

    car = (
        Car.objects.select_related("customer")
        .filter(tracking_code=normalized_code)
        .first()
    )

    if car is None:
        raise ValidationError(
            "Cannot create a lookup log for a vehicle that does not exist."
        )

    return SearchLog.objects.create(
        car=car,
        customer=car.customer,
        source=source,
        user_agent=(user_agent or "")[:300],
    )
