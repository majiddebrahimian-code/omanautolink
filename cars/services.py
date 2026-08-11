import secrets
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from accounts.authorization import (
    require_active_internal_staff,
    require_permission,
)
from customers.models import Customer
from tracking.models import CarStageProgress, Stage
from tracking.services import start_tracking_for_sold_car

from .models import (
    Car,
    CarPhoto,
    CarVideo,
    VehicleArchiveEvent,
    VehicleHold,
    VehicleInventoryEvent,
)


# This is intentionally the single allow-list used by all interfaces that
# create or edit inventory information. Lifecycle state belongs to dedicated
# services below and must never arrive through a generic form payload.
INVENTORY_EDITABLE_FIELDS = (
    "title",
    "brand",
    "model",
    "year",
    "color",
    "mileage",
    "price_amount",
    "description",
    "location",
    "seo_title",
    "seo_description",
    "seo_keywords",
    "is_featured",
)

INVENTORY_EDITABLE_STATUSES = {
    Car.Status.DRAFT,
    Car.Status.FOR_SALE,
}


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


def _validate_inventory_source(*, source):
    valid_sources = {value for value, _label in VehicleInventoryEvent.Source.choices}

    if source not in valid_sources:
        raise ValidationError("منبع ثبت عملیات موجودی معتبر نیست.")

    return source


def _normalise_inventory_value(value):
    """Return JSON-safe values for the immutable inventory audit log."""

    if isinstance(value, Decimal):
        return format(value, "f")

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return value


def _clean_inventory_data(*, vehicle_data):
    """Validate the shared inventory payload before it reaches ``Car``."""

    if not isinstance(vehicle_data, Mapping):
        raise ValidationError("اطلاعات ماشین باید به‌صورت ساختاریافته ارسال شود.")

    unexpected_fields = set(vehicle_data) - set(INVENTORY_EDITABLE_FIELDS)

    if unexpected_fields:
        invalid_names = "، ".join(sorted(unexpected_fields))
        raise ValidationError(
            f"این فیلدها از طریق ویرایش موجودی قابل تغییر نیستند: {invalid_names}"
        )

    cleaned_data = dict(vehicle_data)

    for field_name in (
        "title",
        "brand",
        "model",
        "color",
        "description",
        "location",
        "seo_title",
        "seo_description",
        "seo_keywords",
    ):
        value = cleaned_data.get(field_name)

        if isinstance(value, str):
            cleaned_data[field_name] = value.strip()

    if "price_amount" in cleaned_data and cleaned_data["price_amount"] not in (
        None,
        "",
    ):
        try:
            price_amount = Decimal(str(cleaned_data["price_amount"]))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("قیمت ماشین معتبر نیست.")

        if price_amount < 0:
            raise ValidationError("قیمت ماشین نمی‌تواند منفی باشد.")

        cleaned_data["price_amount"] = price_amount

    return cleaned_data


def _validate_inventory_car(*, car):
    """Run model-level validation while keeping service errors uniform."""

    try:
        car.full_clean()
    except ValidationError as error:
        raise ValidationError(error.messages)


@transaction.atomic
def create_inventory_car(
    *,
    actor,
    vehicle_data,
    source=VehicleInventoryEvent.Source.BACKOFFICE,
):
    """Create a non-public draft car through the shared inventory boundary."""

    require_permission(
        actor=actor,
        permission="cars.add_car",
        error_message="شما اجازهٔ ثبت ماشین جدید را ندارید.",
    )

    cleaned_data = _clean_inventory_data(vehicle_data=vehicle_data)
    validated_source = _validate_inventory_source(source=source)

    car = Car(
        **cleaned_data,
        status=Car.Status.DRAFT,
        is_deleted=False,
    )
    _validate_inventory_car(car=car)
    car.save()

    VehicleInventoryEvent.objects.create(
        car=car,
        action=VehicleInventoryEvent.Action.CREATED,
        performed_by=actor,
        source=validated_source,
        changes={
            "fields": {
                field_name: {
                    "before": None,
                    "after": _normalise_inventory_value(
                        getattr(car, field_name)
                    ),
                }
                for field_name in cleaned_data
            }
        },
    )

    return car


@transaction.atomic
def update_inventory_car(
    *,
    car_id,
    actor,
    vehicle_data,
    source=VehicleInventoryEvent.Source.BACKOFFICE,
):
    """Update mutable inventory fields and record a precise audit diff."""

    require_permission(
        actor=actor,
        permission="cars.change_car",
        error_message="شما اجازهٔ ویرایش اطلاعات ماشین را ندارید.",
    )

    cleaned_data = _clean_inventory_data(vehicle_data=vehicle_data)
    validated_source = _validate_inventory_source(source=source)

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.is_deleted:
        raise ValidationError("ماشین بایگانی‌شده قابل ویرایش نیست.")

    if car.status not in INVENTORY_EDITABLE_STATUSES:
        raise ValidationError(
            "پس از رزرو یا فروش، اطلاعات موجودی ماشین از این صفحه قابل ویرایش نیست."
        )

    changes = {}
    changed_fields = []

    for field_name, new_value in cleaned_data.items():
        old_value = getattr(car, field_name)

        if old_value == new_value:
            continue

        changes[field_name] = {
            "before": _normalise_inventory_value(old_value),
            "after": _normalise_inventory_value(new_value),
        }
        setattr(car, field_name, new_value)
        changed_fields.append(field_name)

    _validate_inventory_car(car=car)

    if not changed_fields:
        return car

    car.save(update_fields=[*changed_fields, "updated_at"])

    VehicleInventoryEvent.objects.create(
        car=car,
        action=VehicleInventoryEvent.Action.UPDATED,
        performed_by=actor,
        source=validated_source,
        changes={"fields": changes},
    )

    return car


def _get_mutable_inventory_car(*, car_id):
    """Lock an active car whose public inventory data may still change."""

    car = Car.objects.select_for_update().get(pk=car_id)

    if car.is_deleted:
        raise ValidationError("ماشین بایگانی‌شده قابل تغییر نیست.")

    if car.status not in INVENTORY_EDITABLE_STATUSES:
        raise ValidationError(
            "پس از رزرو یا فروش، تصاویر موجودی ماشین از این صفحه قابل تغییر نیستند."
        )

    return car


def _record_inventory_photo_event(*, car, actor, source, changes):
    """Add photo activity to the same immutable manager audit stream."""

    VehicleInventoryEvent.objects.create(
        car=car,
        action=VehicleInventoryEvent.Action.UPDATED,
        performed_by=actor,
        source=source,
        changes={"photos": changes},
    )


@transaction.atomic
def upload_car_photos(
    *,
    car_id,
    actor,
    images,
    source=VehicleInventoryEvent.Source.BACKOFFICE,
):
    """Create normal gallery photos for a mutable inventory car.

    360-degree frames intentionally use their own model and services.  They
    must not be inserted into this public gallery because their ordering and
    technical readiness rules are different.
    """

    require_permission(
        actor=actor,
        permission="cars.add_carphoto",
        error_message="شما اجازهٔ افزودن تصویر ماشین را ندارید.",
    )

    image_files = list(images or [])

    if not image_files:
        raise ValidationError("حداقل یک تصویر را انتخاب کنید.")

    validated_source = _validate_inventory_source(source=source)
    car = _get_mutable_inventory_car(car_id=car_id)
    current_max_order = (
        CarPhoto.objects.filter(car=car).aggregate(max_order=Max("sort_order"))["max_order"]
        or 0
    )
    has_cover = CarPhoto.objects.filter(car=car, is_cover=True).exists()
    created_photos = []

    for index, image_file in enumerate(image_files, start=1):
        photo = CarPhoto(
            car=car,
            image=image_file,
            is_cover=not has_cover and index == 1,
            sort_order=current_max_order + index,
        )
        photo.full_clean()
        photo.save()
        created_photos.append(photo)

    _record_inventory_photo_event(
        car=car,
        actor=actor,
        source=validated_source,
        changes={
            "operation": "added",
            "photo_ids": [photo.id for photo in created_photos],
            "count": len(created_photos),
        },
    )

    return created_photos


@transaction.atomic
def upload_car_video(
    *,
    car_id,
    actor,
    video_data,
    source=VehicleInventoryEvent.Source.BACKOFFICE,
):
    """Add one normal vehicle video through the same inventory boundary."""
    require_permission(
        actor=actor,
        permission="cars.add_carvideo",
        error_message="شما اجازهٔ افزودن ویدیوی ماشین را ندارید.",
    )
    if not isinstance(video_data, Mapping):
        raise ValidationError("اطلاعات ویدیوی ماشین معتبر نیست.")

    validated_source = _validate_inventory_source(source=source)
    car = _get_mutable_inventory_car(car_id=car_id)
    video = CarVideo(car=car, **dict(video_data))
    video.full_clean()
    video.save()

    _record_inventory_photo_event(
        car=car,
        actor=actor,
        source=validated_source,
        changes={"operation": "video_added", "video_id": video.pk},
    )
    return video


def _get_mutable_car_photo(*, car_id, photo_id):
    """Lock one photo and verify that its URL cannot target another car."""

    photo = CarPhoto.objects.select_for_update().get(pk=photo_id)

    if photo.car_id != car_id:
        raise ValidationError("این تصویر به ماشین انتخاب‌شده تعلق ندارد.")

    car = _get_mutable_inventory_car(car_id=car_id)
    return car, photo


@transaction.atomic
def update_car_photo_metadata(
    *,
    car_id,
    photo_id,
    actor,
    photo_data,
    source=VehicleInventoryEvent.Source.BACKOFFICE,
):
    """Update a photo's public alt text and sort order through one boundary."""

    require_permission(
        actor=actor,
        permission="cars.change_carphoto",
        error_message="شما اجازهٔ ویرایش اطلاعات تصویر ماشین را ندارید.",
    )

    if not isinstance(photo_data, Mapping):
        raise ValidationError("اطلاعات تصویر معتبر نیست.")

    allowed_fields = {"alt_text", "sort_order"}
    unexpected_fields = set(photo_data) - allowed_fields

    if unexpected_fields:
        raise ValidationError("فیلد نامعتبر برای تصویر ارسال شده است.")

    validated_source = _validate_inventory_source(source=source)
    car, photo = _get_mutable_car_photo(car_id=car_id, photo_id=photo_id)
    changes = {}
    changed_fields = []

    for field_name, new_value in photo_data.items():
        if field_name == "alt_text" and isinstance(new_value, str):
            new_value = new_value.strip()

        old_value = getattr(photo, field_name)

        if old_value == new_value:
            continue

        setattr(photo, field_name, new_value)
        changes[field_name] = {
            "before": _normalise_inventory_value(old_value),
            "after": _normalise_inventory_value(new_value),
        }
        changed_fields.append(field_name)

    try:
        photo.full_clean()
    except ValidationError as error:
        raise ValidationError(error.messages)

    if not changed_fields:
        return photo

    photo.save(update_fields=changed_fields)
    _record_inventory_photo_event(
        car=car,
        actor=actor,
        source=validated_source,
        changes={
            "operation": "metadata_updated",
            "photo_id": photo.id,
            "fields": changes,
        },
    )

    return photo


@transaction.atomic
def set_car_photo_cover(
    *,
    car_id,
    photo_id,
    actor,
    source=VehicleInventoryEvent.Source.BACKOFFICE,
):
    """Make exactly one normal gallery photo the public cover image."""

    require_permission(
        actor=actor,
        permission="cars.change_carphoto",
        error_message="شما اجازهٔ انتخاب تصویر کاور را ندارید.",
    )

    validated_source = _validate_inventory_source(source=source)
    car, photo = _get_mutable_car_photo(car_id=car_id, photo_id=photo_id)

    if photo.is_cover:
        return photo

    CarPhoto.objects.filter(car=car, is_cover=True).update(is_cover=False)
    photo.is_cover = True
    photo.save(update_fields=["is_cover"])

    _record_inventory_photo_event(
        car=car,
        actor=actor,
        source=validated_source,
        changes={
            "operation": "cover_changed",
            "photo_id": photo.id,
        },
    )

    return photo


@transaction.atomic
def delete_car_photo(
    *,
    car_id,
    photo_id,
    actor,
    source=VehicleInventoryEvent.Source.BACKOFFICE,
):
    """Remove one gallery record and delete its stored file after commit."""

    require_permission(
        actor=actor,
        permission="cars.delete_carphoto",
        error_message="شما اجازهٔ حذف تصویر ماشین را ندارید.",
    )

    validated_source = _validate_inventory_source(source=source)
    car, photo = _get_mutable_car_photo(car_id=car_id, photo_id=photo_id)
    deleted_photo_id = photo.id
    deleted_was_cover = photo.is_cover
    image_storage = photo.image.storage if photo.image else None
    image_name = photo.image.name if photo.image else ""

    photo.delete()

    if deleted_was_cover:
        replacement_photo = CarPhoto.objects.filter(car=car).order_by(
            "sort_order",
            "pk",
        ).first()

        if replacement_photo is not None:
            replacement_photo.is_cover = True
            replacement_photo.save(update_fields=["is_cover"])

    _record_inventory_photo_event(
        car=car,
        actor=actor,
        source=validated_source,
        changes={
            "operation": "deleted",
            "photo_id": deleted_photo_id,
            "replacement_cover_photo_id": (
                replacement_photo.id if deleted_was_cover and replacement_photo else None
            ),
        },
    )

    if image_storage is not None and image_name:
        transaction.on_commit(lambda: image_storage.delete(image_name))

    return car


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

    from integrations.services import queue_vehicle_channel_sale_state_change
    queue_vehicle_channel_sale_state_change(car_id=car.pk, actor=actor)

    return car


def get_vehicle_sale_reversal_eligibility(*, car):
    """Return whether a sale may be reversed before any later stage begins."""
    if car.is_deleted or car.status != Car.Status.SOLD:
        return False, "فقط خودروی فروخته‌شده قابل بازگشت است."

    first_stage = Stage.objects.filter(is_active=True).order_by("order", "pk").first()
    if first_stage is None or car.current_stage_id != first_stage.pk:
        return False, "بازگشت از فروش فقط در مرحلهٔ اول مجاز است."

    later_stage_progress_exists = CarStageProgress.objects.filter(car=car).exclude(
        stage_id=first_stage.pk
    ).filter(
        Q(actual_arrival__isnull=False)
        | Q(completed_at__isnull=False)
        | Q(skipped_at__isnull=False)
    ).exists()
    if later_stage_progress_exists:
        return False, "برای این خودرو مرحلهٔ بعدی شروع شده است و بازگشت مجاز نیست."

    return True, ""


@transaction.atomic
def reverse_vehicle_sale(*, car_id, actor, reason, source=VehicleInventoryEvent.Source.BACKOFFICE):
    """Return a mistakenly sold vehicle to inventory during its first stage only."""
    require_permission(
        actor=actor,
        permission="cars.reverse_vehicle_sale",
        error_message="شما اجازهٔ بازگشت از فروش را ندارید.",
    )
    _validate_inventory_source(source=source)
    cleaned_reason = str(reason or "").strip()
    if len(cleaned_reason) < 10:
        raise ValidationError("دلیل بازگشت از فروش باید حداقل 10 کاراکتر باشد.")

    car = Car.objects.select_for_update().select_related("customer", "current_stage").get(pk=car_id)
    allowed, rejection_reason = get_vehicle_sale_reversal_eligibility(car=car)
    if not allowed:
        raise ValidationError(rejection_reason)

    previous_tracking_code = car.tracking_code
    previous_customer_id = car.customer_id
    now = timezone.now()

    from customers.models import CustomVehicleRequest
    from integrations.models import CustomerTelegramSubscription, TelegramCustomerActivationToken

    # The first automatic tracking records are operational state, not the sale
    # audit. They must be cleared so a future valid sale can start a new route.
    CarStageProgress.objects.filter(car=car).delete()

    TelegramCustomerActivationToken.objects.select_for_update().filter(
        car=car,
        revoked_at__isnull=True,
    ).update(revoked_at=now, revoked_by=actor)
    CustomerTelegramSubscription.objects.select_for_update().filter(
        car=car,
        is_active=True,
    ).update(
        is_active=False,
        unsubscribed_at=now,
        unsubscribe_reason="بازگشت از فروش توسط مدیریت سیستم.",
    )

    custom_request = CustomVehicleRequest.objects.select_for_update().filter(sold_car=car).first()
    if custom_request is not None:
        custom_request.status = CustomVehicleRequest.Status.NEW
        custom_request.sold_car = None
        custom_request.sold_at = None
        custom_request.sold_by = None
        custom_request.save(update_fields=["status", "sold_car", "sold_at", "sold_by", "updated_at"])

    car.customer = None
    car.current_stage = None
    car.target_delivery = None
    car.tracking_code = None
    car.status = Car.Status.FOR_SALE
    car.save(update_fields=["customer", "current_stage", "target_delivery", "tracking_code", "status"])

    VehicleInventoryEvent.objects.create(
        car=car,
        action=VehicleInventoryEvent.Action.SALE_REVERSED,
        performed_by=actor,
        source=source,
        changes={
            "reason": cleaned_reason,
            "previous_status": Car.Status.SOLD,
            "new_status": Car.Status.FOR_SALE,
            "previous_tracking_code": previous_tracking_code,
            "previous_customer_id": previous_customer_id,
            "custom_request_reopened": custom_request is not None,
        },
    )

    from integrations.services import queue_vehicle_channel_sale_state_change
    queue_vehicle_channel_sale_state_change(car_id=car.pk, actor=actor)
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
def create_inventory_car_and_publish_to_telegram(*, actor, vehicle_data, source):
    """Create a vehicle, make it public, and queue its first channel post."""
    car = create_inventory_car(
        actor=actor,
        vehicle_data=vehicle_data,
        source=source,
    )
    car = publish_vehicle_for_sale(car_id=car.pk, actor=actor)

    from integrations.services import queue_vehicle_channel_publication

    publication, outbox_message = queue_vehicle_channel_publication(
        car_id=car.pk,
        actor=actor,
    )
    return car, publication, outbox_message


@transaction.atomic
def update_inventory_car_and_publish_to_telegram(*, car_id, actor, vehicle_data, source):
    """Save inventory changes and publish or update the matching channel post."""
    car = update_inventory_car(
        car_id=car_id,
        actor=actor,
        vehicle_data=vehicle_data,
        source=source,
    )
    if car.status == Car.Status.DRAFT:
        car = publish_vehicle_for_sale(car_id=car.pk, actor=actor)

    from integrations.services import queue_vehicle_channel_publication

    publication, outbox_message = queue_vehicle_channel_publication(
        car_id=car.pk,
        actor=actor,
    )
    return car, publication, outbox_message


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
