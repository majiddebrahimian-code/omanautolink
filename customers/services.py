from decimal import Decimal, InvalidOperation
from django.utils import timezone

from tracking.models import TrackingEvent

from django.core.exceptions import ValidationError
from django.db import transaction

from cars.models import Car

from .models import (
    CustomVehicleRequest,
    CustomVehicleRequestReadReceipt,
    SearchLog,
)


def _required_text(value, field_name, error_message):
    normalized_value = str(value or "").strip()

    if not normalized_value:
        raise ValidationError(
            {
                field_name: error_message,
            }
        )

    return normalized_value


def _optional_text(value):
    return str(value or "").strip()


def _optional_year(value, field_name):
    if value in [None, ""]:
        return None

    try:
        normalized_year = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            {
                field_name: "سال واردشده معتبر نیست.",
            }
        )

    if normalized_year <= 0:
        raise ValidationError(
            {
                field_name: "سال واردشده معتبر نیست.",
            }
        )

    return normalized_year


def _positive_budget(value):
    try:
        normalized_budget = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(
            {
                "budget_amount": "بودجه واردشده معتبر نیست.",
            }
        )

    if normalized_budget <= 0:
        raise ValidationError(
            {
                "budget_amount": "بودجه باید بزرگ‌تر از صفر باشد.",
            }
        )

    return normalized_budget


@transaction.atomic
def create_custom_vehicle_request(
    *,
    full_name,
    phone,
    desired_vehicle_description,
    preferred_brand="",
    preferred_model="",
    preferred_year_from=None,
    preferred_year_to=None,
    budget_amount=None,
    preferred_color="",
    notes="",
    telegram_id="",
    source=CustomVehicleRequest.Source.WEBSITE,
):
    """
    Creates a customer lead for a vehicle that may not exist in inventory.

    This service is intentionally shared by Website and Telegram Bot.
    It does not create a Customer record and does not require a Car.
    """

    if source not in CustomVehicleRequest.Source.values:
        raise ValidationError(
            {
                "source": "منبع ثبت درخواست معتبر نیست.",
            }
        )

    normalized_year_from = _optional_year(
        preferred_year_from,
        "preferred_year_from",
    )
    normalized_year_to = _optional_year(
        preferred_year_to,
        "preferred_year_to",
    )

    if (
        normalized_year_from is not None
        and normalized_year_to is not None
        and normalized_year_from > normalized_year_to
    ):
        raise ValidationError(
            {"preferred_year_to": ("سال پایان نمی‌تواند از سال شروع کمتر باشد.")}
        )

    vehicle_request = CustomVehicleRequest(
        full_name=_required_text(
            full_name,
            "full_name",
            "نام و نام خانوادگی الزامی است.",
        ),
        phone=_required_text(
            phone,
            "phone",
            "شماره تلفن الزامی است.",
        ),
        telegram_id=_optional_text(telegram_id),
        desired_vehicle_description=_required_text(
            desired_vehicle_description,
            "desired_vehicle_description",
            "توضیح خودروی موردنظر الزامی است.",
        ),
        preferred_brand=_optional_text(preferred_brand),
        preferred_model=_optional_text(preferred_model),
        preferred_year_from=normalized_year_from,
        preferred_year_to=normalized_year_to,
        budget_amount=_positive_budget(budget_amount),
        preferred_color=_optional_text(preferred_color),
        notes=_optional_text(notes),
        source=source,
        status=CustomVehicleRequest.Status.NEW,
    )

    vehicle_request.full_clean()
    vehicle_request.save()

    return vehicle_request


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


@transaction.atomic
def record_custom_vehicle_request_view(
    *,
    vehicle_request_id,
    employee,
):
    """
    Records that an authorized employee opened a custom vehicle request.

    This is an audit record, not an employee assignment.
    Repeated views by the same employee update one existing receipt.
    """

    if employee is None or not employee.is_authenticated:
        raise ValidationError("برای مشاهدهٔ درخواست باید وارد سیستم شوید.")

    if not employee.has_perm("customers.view_customvehiclerequest"):
        raise ValidationError("شما اجازهٔ مشاهدهٔ درخواست‌های خودرو را ندارید.")

    try:
        vehicle_request = CustomVehicleRequest.objects.select_for_update().get(
            pk=vehicle_request_id
        )
    except CustomVehicleRequest.DoesNotExist:
        raise ValidationError("درخواست خودروی موردنظر پیدا نشد.")

    receipt, created = CustomVehicleRequestReadReceipt.objects.get_or_create(
        vehicle_request=vehicle_request,
        employee=employee,
    )

    if not created:
        receipt.save(
            update_fields=[
                "last_seen_at",
            ]
        )

    return receipt


@transaction.atomic
def convert_custom_vehicle_request_to_sold(
    *,
    vehicle_request_id,
    car_id,
    actor,
    telegram_id,
    tracking_source=TrackingEvent.Source.ADMIN_DASHBOARD,
):
    """
    Converts a New custom vehicle request into a completed sale.

    The selected vehicle must already be On Hold.
    This function reuses the existing mark_vehicle_as_sold service,
    so Customer creation, tracking-code generation, and tracking
    startup are never duplicated here.
    """

    if actor is None or not actor.is_authenticated:
        raise ValidationError("برای ثبت فروش باید وارد سیستم شوید.")

    if not actor.has_perm("customers.change_customvehiclerequest"):
        raise ValidationError("شما اجازهٔ تبدیل درخواست به فروش را ندارید.")

    try:
        vehicle_request = CustomVehicleRequest.objects.select_for_update().get(
            pk=vehicle_request_id
        )
    except CustomVehicleRequest.DoesNotExist:
        raise ValidationError("درخواست خودروی موردنظر پیدا نشد.")

    if vehicle_request.status != CustomVehicleRequest.Status.NEW:
        raise ValidationError("فقط درخواست‌های جدید قابل تبدیل به فروش هستند.")

    try:
        car = Car.objects.select_for_update().get(pk=car_id)
    except Car.DoesNotExist:
        raise ValidationError("خودروی موردنظر پیدا نشد.")

    if car.status != Car.Status.ON_HOLD:
        raise ValidationError("خودرو باید ابتدا به‌صورت موقت رزرو شده باشد.")

    if CustomVehicleRequest.objects.filter(sold_car=car).exists():
        raise ValidationError("این خودرو قبلاً به یک درخواست سفارشی دیگر متصل شده است.")

    normalized_telegram_id = _required_text(
        telegram_id,
        "telegram_id",
        "شناسهٔ تلگرام مشتری برای ثبت فروش الزامی است.",
    )

    # Local import prevents unnecessary coupling during Django app startup.
    from cars.services import mark_vehicle_as_sold

    sold_car = mark_vehicle_as_sold(
        car_id=car.id,
        actor=actor,
        full_name=vehicle_request.full_name,
        phone=vehicle_request.phone,
        telegram_id=normalized_telegram_id,
        source=tracking_source,
    )

    vehicle_request.telegram_id = normalized_telegram_id
    vehicle_request.status = CustomVehicleRequest.Status.SOLD
    vehicle_request.sold_car = sold_car
    vehicle_request.sold_at = timezone.now()
    vehicle_request.sold_by = actor

    vehicle_request.full_clean()
    vehicle_request.save(
        update_fields=[
            "telegram_id",
            "status",
            "sold_car",
            "sold_at",
            "sold_by",
            "updated_at",
        ]
    )

    return sold_car
