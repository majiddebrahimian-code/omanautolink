import secrets

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.authorization import (
    require_active_internal_staff,
    require_permission,
)
from customers.models import Customer
from tracking.services import start_tracking_for_sold_car

from .models import Car, VehicleArchiveEvent, VehicleHold


def generate_tracking_code():
    """
    Generates a random public tracking code.

    The code is intentionally hard to guess because customers use it
    to view shipment progress without a customer login.
    """

    while True:
        code = f"OAL-{secrets.token_urlsafe(16)}"

        if not Car.objects.filter(tracking_code=code).exists():
            return code


def _clean_required_reason(*, reason):
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("ثبت دلیل برای این عملیات الزامی است.")

    return reason.strip()


def _validate_archive_source(*, source):
    valid_sources = {value for value, _label in VehicleArchiveEvent.Source.choices}

    if source not in valid_sources:
        raise ValidationError("منبع ثبت عملیات بایگانی معتبر نیست.")

    return source


def _require_system_administrator(*, actor):
    require_active_internal_staff(actor=actor)

    if not actor.is_superuser:
        raise ValidationError("فقط مدیر اصلی سیستم اجازهٔ بازگردانی خودرو را دارد.")


@transaction.atomic
def archive_vehicle(
    *,
    car_id,
    actor,
    reason,
    source=VehicleArchiveEvent.Source.SYSTEM,
):
    """
    Soft-archives an inventory vehicle.

    Only DRAFT and FOR_SALE vehicles may be archived. The business
    status stays unchanged, while is_deleted hides the vehicle from
    inventory-facing interfaces.
    """

    require_permission(
        actor=actor,
        permission="cars.archive_vehicle",
        error_message="شما اجازهٔ بایگانی خودرو را ندارید.",
    )

    cleaned_reason = _clean_required_reason(reason=reason)
    validated_source = _validate_archive_source(source=source)

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.is_deleted:
        raise ValidationError("این خودرو قبلاً بایگانی شده است.")

    if car.status not in {
        Car.Status.DRAFT,
        Car.Status.FOR_SALE,
    }:
        raise ValidationError(
            "فقط خودروهای پیش‌نویس یا موجود برای فروش قابل بایگانی هستند."
        )

    if VehicleHold.objects.filter(
        car=car,
        is_active=True,
    ).exists():
        raise ValidationError("خودروی دارای رزرو موقت فعال قابل بایگانی نیست.")

    previous_status = car.status

    car.is_deleted = True
    car.save(update_fields=["is_deleted"])

    VehicleArchiveEvent.objects.create(
        car=car,
        action=VehicleArchiveEvent.Action.ARCHIVED,
        previous_status=previous_status,
        new_status=car.status,
        performed_by=actor,
        source=validated_source,
        reason=cleaned_reason,
    )

    return car


@transaction.atomic
def restore_archived_vehicle(
    *,
    car_id,
    actor,
    reason,
    source=VehicleArchiveEvent.Source.SYSTEM,
):
    """
    Restores an archived inventory vehicle.

    Restoration is restricted to the System Administrator. Every
    restored vehicle becomes DRAFT and requires an explicit publish
    action before it can appear in inventory again.
    """

    _require_system_administrator(actor=actor)

    cleaned_reason = _clean_required_reason(reason=reason)
    validated_source = _validate_archive_source(source=source)

    car = Car.objects.select_for_update().get(pk=car_id)

    if not car.is_deleted:
        raise ValidationError("این خودرو بایگانی نشده است.")

    if car.status not in {
        Car.Status.DRAFT,
        Car.Status.FOR_SALE,
    }:
        raise ValidationError("فقط خودروهای بایگانی‌شدهٔ موجودی قابل بازگردانی هستند.")

    previous_status = car.status

    car.is_deleted = False
    car.status = Car.Status.DRAFT
    car.save(update_fields=["is_deleted", "status"])

    VehicleArchiveEvent.objects.create(
        car=car,
        action=VehicleArchiveEvent.Action.RESTORED,
        previous_status=previous_status,
        new_status=car.status,
        performed_by=actor,
        source=validated_source,
        reason=cleaned_reason,
    )

    return car


@transaction.atomic
def mark_vehicle_as_sold(
    *,
    car_id,
    actor,
    full_name,
    phone,
    telegram_id,
    source="system",
):
    """
    Converts an active vehicle hold into a completed sale.

    A customer is created or found by Telegram ID.
    A unique tracking code is assigned to the vehicle.
    """

    require_permission(
        actor=actor,
        permission="cars.sell_vehicle",
        error_message="شما اجازهٔ ثبت فروش خودرو را ندارید.",
    )

    if not full_name.strip():
        raise ValidationError("نام کامل مشتری الزامی است.")

    if not phone.strip():
        raise ValidationError("شماره تلفن مشتری الزامی است.")

    if not telegram_id.strip():
        raise ValidationError("شناسهٔ تلگرام مشتری الزامی است.")

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.is_deleted:
        raise ValidationError("خودروی بایگانی‌شده قابل ثبت فروش نیست.")

    if car.status != Car.Status.ON_HOLD:
        raise ValidationError("فقط خودرویی که در وضعیت رزرو موقت است قابل فروش است.")

    active_hold = (
        VehicleHold.objects.select_for_update().filter(car=car, is_active=True).first()
    )

    if active_hold is None:
        raise ValidationError("این خودرو رزرو موقت فعال ندارد.")

    customer, _ = Customer.objects.get_or_create(
        telegram_id=telegram_id.strip(),
        defaults={
            "full_name": full_name.strip(),
            "phone": phone.strip(),
        },
    )

    car.customer = customer
    car.status = Car.Status.SOLD
    car.tracking_code = generate_tracking_code()
    car.save(
        update_fields=[
            "customer",
            "status",
            "tracking_code",
        ]
    )

    active_hold.is_active = False
    active_hold.released_at = timezone.now()
    active_hold.released_by = actor
    active_hold.release_note = "تبدیل رزرو موقت به فروش."
    active_hold.save(
        update_fields=[
            "is_active",
            "released_at",
            "released_by",
            "release_note",
        ]
    )

    start_tracking_for_sold_car(
        car=car,
        actor=actor,
        source=source,
    )

    # A sale already required the explicit sell_vehicle permission above.  It
    # therefore issues the one-time customer activation code as part of the
    # same transaction, without granting a broader reissue permission.
    from integrations.services import create_customer_telegram_activation_code

    activation_result = create_customer_telegram_activation_code(
        car=car,
        actor=actor,
        enforce_issue_permission=False,
    )

    car.refresh_from_db()
    # The raw code is intentionally an in-memory, one-time handoff only.  It
    # is never a Car field and is never written to the database or audit log.
    car.telegram_customer_activation_code = activation_result["code"]
    car.telegram_customer_activation_expires_at = activation_result["expires_at"]

    return car


@transaction.atomic
def publish_vehicle_for_sale(*, car_id, actor):
    """
    Publishes a draft vehicle and makes it available for sale.
    """

    require_permission(
        actor=actor,
        permission="cars.publish_vehicle",
        error_message="شما اجازهٔ انتشار خودرو برای فروش را ندارید.",
    )

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.is_deleted:
        raise ValidationError("خودروی بایگانی‌شده قابل انتشار نیست.")

    if car.status != Car.Status.DRAFT:
        raise ValidationError("فقط خودروی پیش‌نویس قابل انتشار برای فروش است.")

    car.status = Car.Status.FOR_SALE
    car.save(update_fields=["status"])

    return car


@transaction.atomic
def place_vehicle_on_hold(
    *,
    car_id,
    actor,
    customer_name="",
    customer_phone="",
    expires_at=None,
):
    """
    Creates an active temporary hold for a vehicle.

    The vehicle must currently be available for sale.
    """

    require_permission(
        actor=actor,
        permission="cars.hold_vehicle",
        error_message="شما اجازهٔ ثبت رزرو موقت خودرو را ندارید.",
    )

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.is_deleted:
        raise ValidationError("خودروی بایگانی‌شده قابل رزرو موقت نیست.")

    if car.status != Car.Status.FOR_SALE:
        raise ValidationError("فقط خودروی موجود برای فروش قابل رزرو موقت است.")

    if VehicleHold.objects.filter(
        car=car,
        is_active=True,
    ).exists():
        raise ValidationError("این خودرو از قبل رزرو موقت فعال دارد.")

    hold = VehicleHold.objects.create(
        car=car,
        customer_name=customer_name,
        customer_phone=customer_phone,
        created_by=actor,
        expires_at=expires_at,
    )

    car.status = Car.Status.ON_HOLD
    car.save(update_fields=["status"])

    return hold


@transaction.atomic
def release_vehicle_hold(*, hold_id, actor, release_note=""):
    """
    Releases an active vehicle hold and returns the vehicle to For Sale.
    """

    require_permission(
        actor=actor,
        permission="cars.release_vehicle_hold",
        error_message="شما اجازهٔ آزادسازی رزرو موقت خودرو را ندارید.",
    )

    hold = VehicleHold.objects.select_for_update().get(pk=hold_id)
    car = Car.objects.select_for_update().get(pk=hold.car_id)

    if car.is_deleted:
        raise ValidationError("رزرو مربوط به خودروی بایگانی‌شده قابل آزادسازی نیست.")

    if not hold.is_active:
        raise ValidationError("این رزرو موقت قبلاً آزاد شده است.")

    hold.is_active = False
    hold.released_at = timezone.now()
    hold.released_by = actor
    hold.release_note = release_note
    hold.save(
        update_fields=[
            "is_active",
            "released_at",
            "released_by",
            "release_note",
        ]
    )

    car.status = Car.Status.FOR_SALE
    car.save(update_fields=["status"])

    return hold
