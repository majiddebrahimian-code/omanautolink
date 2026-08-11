"""Shared application services for Telegram integration workflows.

The Telegram adapter is intentionally thin.  It obtains a verified staff
identity here, creates a short-lived confirmation session here, and delegates
the final tracking change to ``tracking.services.confirm_stage``.
"""

import logging
import mimetypes
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.signing import salted_hmac
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.authorization import require_active_internal_staff, require_permission

from .models import (
    CustomerTelegramSubscription,
    CustomerTrackingNotification,
    TelegramCustomerActivationToken,
    TelegramInboundUpdate,
    TelegramIntegrationSettings,
    TelegramOutboxMessage,
    TelegramStageConfirmationSession,
    TelegramStaffLink,
    TelegramStaffLinkToken,
    TelegramVehiclePublication,
)


logger = logging.getLogger(__name__)


def get_telegram_integration_settings():
    """Return the singleton operational configuration; secrets stay in .env."""

    settings_record, _ = TelegramIntegrationSettings.objects.get_or_create(pk=1)
    return settings_record


def _get_configured_telegram_gateway(*, gateway=None):
    """Return a gateway only when the environment-owned Bot config is ready."""
    if not settings.TELEGRAM_BOT_ENABLED or not settings.TELEGRAM_BOT_TOKEN:
        raise ValidationError("Bot تلگرام در فایل .env فعال یا تنظیم نشده است.")

    if gateway is not None:
        return gateway

    from .telegram.gateway import TelegramHTTPGateway

    return TelegramHTTPGateway()


def test_telegram_bot_connection(*, actor, gateway=None):
    """Safely verify the configured Bot identity for a System Administrator."""
    _require_system_administrator(actor=actor)
    gateway = _get_configured_telegram_gateway(gateway=gateway)

    try:
        bot = gateway.get_me()
    except Exception as error:
        logger.warning("Telegram Bot connectivity test failed.")
        raise ValidationError(
            "اتصال به Bot تلگرام برقرار نشد. Token، اینترنت و فعال‌بودن Bot را بررسی کنید."
        ) from error

    if not isinstance(bot, dict) or not bot.get("id"):
        raise ValidationError("پاسخ Bot تلگرام معتبر نبود.")

    return {
        "bot_id": bot["id"],
        "username": str(bot.get("username") or ""),
        "first_name": str(bot.get("first_name") or ""),
    }


def test_telegram_channel_access(*, actor, channel_id, gateway=None):
    """Verify a Bot can publish and maintain posts in one configured channel."""
    from .models import TelegramChannel

    _require_system_administrator(actor=actor)
    channel = TelegramChannel.objects.get(pk=channel_id)
    gateway = _get_configured_telegram_gateway(gateway=gateway)

    try:
        bot = gateway.get_me()
        gateway.get_chat(chat_id=channel.chat_id)
        membership = gateway.get_chat_member(
            chat_id=channel.chat_id,
            user_id=bot["id"],
        )
    except Exception as error:
        logger.warning("Telegram channel access test failed for channel_id=%s.", channel.pk)
        raise ValidationError(
            "بررسی کانال ناموفق بود. مطمئن شوید Bot به کانال افزوده شده و شناسهٔ کانال صحیح است."
        ) from error

    if not isinstance(membership, dict):
        raise ValidationError("پاسخ دسترسی کانال Telegram معتبر نبود.")

    membership_status = str(membership.get("status") or "")
    is_owner = membership_status in {"creator", "owner"}
    is_administrator = membership_status == "administrator"
    can_post = is_owner or bool(membership.get("can_post_messages"))
    can_edit = is_owner or bool(membership.get("can_edit_messages"))
    can_delete = is_owner or bool(membership.get("can_delete_messages"))

    if not (is_owner or is_administrator):
        raise ValidationError("Bot باید مدیر کانال Telegram باشد.")
    if not can_post:
        raise ValidationError("Bot اجازهٔ ارسال پست در این کانال را ندارد.")

    return {
        "channel": channel,
        "can_post": can_post,
        "can_edit": can_edit,
        "can_delete": can_delete,
        "is_fully_ready": can_edit and can_delete,
    }


def _vehicle_publication_body(*, car):
    """Create the title, specifications, description, then public contact CTA."""
    details = [
        f"🚗 {car.title}",
        "",
        f"🏷 برند: {car.brand}",
        f"📌 مدل: {car.model}",
    ]

    if car.year:
        details.append(f"📅 سال ساخت: {car.year}")
    if car.color:
        details.append(f"🎨 رنگ: {car.color}")
    if car.mileage:
        details.append(f"📏 کارکرد: {car.mileage:,} کیلومتر")
    if car.price_amount:
        details.append(f"💰 قیمت: {car.price_amount:,.0f}")
    if car.location:
        details.append(f"📍 محل خودرو: {car.location}")

    description = (car.description or "").strip()
    if description:
        details.extend(["", f"📄 {description[:700]}"])

    details.extend(
        ["", "💬 برای دریافت مشاوره و ثبت درخواست، با مشاوران ما در تلگرام تماس بگیرید."]
    )
    # Captions attached to Telegram photos/videos have a 1,024-character limit.
    return "\n".join(details)[:1024]


def _unpublished_vehicle_media_refs(*, car):
    """Return stable references for gallery files not yet known by Telegram."""
    from cars.models import CarPhoto, CarVideo

    references = []
    for photo in CarPhoto.objects.filter(
        car=car,
        telegram_file_id__isnull=True,
        image__isnull=False,
    ).exclude(image="").order_by("sort_order", "pk"):
        references.append({"type": "car_photo", "id": photo.pk})
    for video in CarVideo.objects.filter(
        car=car,
        telegram_file_id__isnull=True,
        video__isnull=False,
    ).exclude(video="").order_by("sort_order", "pk"):
        references.append({"type": "car_video", "id": video.pk})
    return references


def _vehicle_media_refs(*, car):
    """Return every publishable local vehicle media reference in display order."""
    from cars.models import CarPhoto, CarVideo

    references = []
    for photo in CarPhoto.objects.filter(
        car=car,
        image__isnull=False,
    ).exclude(image="").order_by("sort_order", "pk"):
        references.append({"type": "car_photo", "id": photo.pk})
    for video in CarVideo.objects.filter(
        car=car,
        video__isnull=False,
    ).exclude(video="").order_by("sort_order", "pk"):
        references.append({"type": "car_video", "id": video.pk})
    return references


@transaction.atomic
def queue_vehicle_channel_publication(*, car_id, actor, enforce_permission=True):
    """Queue one vehicle post or safely rebuild a legacy text-only post as media."""
    if enforce_permission:
        require_permission(
            actor=actor,
            permission="cars.publish_vehicle",
            error_message="شما اجازهٔ انتشار خودرو در Telegram را ندارید.",
        )

    if not settings.TELEGRAM_BOT_ENABLED or not settings.TELEGRAM_BOT_TOKEN:
        raise ValidationError("Bot Telegram در فایل .env فعال یا تنظیم نشده است.")

    settings_record = TelegramIntegrationSettings.objects.select_for_update().get_or_create(
        pk=1
    )[0]
    channel = settings_record.default_vehicle_channel

    if not settings_record.vehicle_channel_sync_enabled:
        raise ValidationError("همگام‌سازی خودرو با کانال Telegram فعال نشده است.")
    if channel is None or not channel.is_active or not channel.publish_available_vehicles:
        raise ValidationError("یک کانال فعال و مجاز برای انتشار خودرو انتخاب کنید.")

    from cars.models import Car

    car = Car.objects.select_for_update().get(pk=car_id)
    if car.is_deleted or car.status != Car.Status.FOR_SALE:
        raise ValidationError("??? ???????? ????? ???? ???? ?? Telegram ????? ???????.")

    publication = (
        TelegramVehiclePublication.objects.select_for_update()
        .filter(car=car, channel=channel)
        .first()
    )
    if publication is None:
        publication = TelegramVehiclePublication.objects.create(car=car, channel=channel)

    body = _vehicle_publication_body(car=car)
    all_media_refs = _vehicle_media_refs(car=car)
    unsent_media_refs = _unpublished_vehicle_media_refs(car=car)
    previous_outbox = publication.latest_outbox_message

    if (
        publication.telegram_message_id is None
        and previous_outbox is not None
        and previous_outbox.status
        in {TelegramOutboxMessage.Status.PENDING, TelegramOutboxMessage.Status.RETRY}
    ):
        previous_outbox.body = body
        previous_outbox.save(update_fields=["body"])
        _queue_unsent_vehicle_media(
            car=car,
            channel=channel,
            excluded_refs=_outbox_media_refs(outbox_message=previous_outbox),
        )
        return publication, previous_outbox

    legacy_text_post_needs_rebuild = (
        publication.telegram_message_id is not None
        and publication.content_mode == "message"
        and bool(all_media_refs)
    )
    if (
        publication.telegram_message_id is not None
        and previous_outbox is not None
        and previous_outbox.status == TelegramOutboxMessage.Status.SENT
        and previous_outbox.body == body
        and not legacy_text_post_needs_rebuild
    ):
        _queue_unsent_vehicle_media(car=car, channel=channel)
        return publication, previous_outbox

    publication.revision += 1
    if publication.telegram_message_id is None:
        candidate_refs = unsent_media_refs
        message_type_prefix = "publish"
        replacement_target_message_id = None
    elif legacy_text_post_needs_rebuild:
        candidate_refs = all_media_refs
        message_type_prefix = "media_republish"
        replacement_target_message_id = publication.telegram_message_id
    else:
        candidate_refs = []

    if candidate_refs:
        initial_refs = candidate_refs[:10]
        operation = (
            TelegramOutboxMessage.Operation.SEND_MEDIA_GROUP
            if len(initial_refs) > 1
            else (
                TelegramOutboxMessage.Operation.SEND_PHOTO
                if initial_refs[0]["type"] == "car_photo"
                else TelegramOutboxMessage.Operation.SEND_VIDEO
            )
        )
        message_type = f"vehicle_channel_{message_type_prefix}"
        idempotency_key = (
            f"vehicle-channel:{channel.pk}:car:{car.pk}:{message_type_prefix}:"
            f"{publication.revision}"
        )
        target_message_id = replacement_target_message_id
    elif publication.telegram_message_id is None:
        initial_refs = []
        operation = TelegramOutboxMessage.Operation.SEND_MESSAGE
        message_type = "vehicle_channel_publish"
        idempotency_key = f"vehicle-channel:{channel.pk}:car:{car.pk}:publish:{publication.revision}"
        target_message_id = None
    else:
        initial_refs = []
        operation = (
            TelegramOutboxMessage.Operation.EDIT_MEDIA_CAPTION
            if publication.content_mode == "caption"
            else TelegramOutboxMessage.Operation.EDIT_MESSAGE
        )
        message_type = "vehicle_channel_update"
        idempotency_key = f"vehicle-channel:{channel.pk}:car:{car.pk}:update:{publication.revision}"
        target_message_id = publication.telegram_message_id

    outbox_message = queue_telegram_message(
        chat_id=channel.chat_id,
        body=body,
        message_type=message_type,
        idempotency_key=idempotency_key,
        target_message_id=target_message_id,
        operation=operation,
        media_object_type=(initial_refs[0]["type"] if len(initial_refs) == 1 else ""),
        media_object_id=(initial_refs[0]["id"] if len(initial_refs) == 1 else None),
        media_object_refs=(initial_refs if len(initial_refs) > 1 else None),
    )
    publication.latest_outbox_message = outbox_message
    publication.save(update_fields=["latest_outbox_message", "revision", "updated_at"])
    _queue_unsent_vehicle_media(
        car=car,
        channel=channel,
        excluded_refs=initial_refs,
    )
    return publication, outbox_message


@transaction.atomic
def queue_vehicle_channel_sale_state_change(*, car_id, actor):
    """Queue the configured channel action after sale or first-stage reversal.

    This is called only by the authorized shared sale services. It never makes
    an HTTP request; it creates durable outbox work for the Worker.
    """
    from cars.models import Car

    settings_record = TelegramIntegrationSettings.objects.select_for_update().filter(pk=1).first()
    if (
        settings_record is None
        or not settings_record.vehicle_channel_sync_enabled
        or settings_record.default_vehicle_channel_id is None
    ):
        return None

    car = Car.objects.select_for_update().get(pk=car_id)
    channel = settings_record.default_vehicle_channel
    publication = (
        TelegramVehiclePublication.objects.select_for_update()
        .filter(car=car, channel=channel)
        .first()
    )

    if car.status == Car.Status.FOR_SALE and (
        publication is None or publication.telegram_message_id is None
    ):
        return queue_vehicle_channel_publication(
            car_id=car.pk,
            actor=actor,
            enforce_permission=False,
        )[1]

    if publication is None or publication.telegram_message_id is None:
        return None

    publication.revision += 1
    if car.status == Car.Status.SOLD:
        if (
            settings_record.sold_vehicle_publication_action
            == TelegramIntegrationSettings.SoldPublicationAction.DELETE
        ):
            outbox_message = queue_telegram_message(
                chat_id=channel.chat_id,
                body="",
                message_type="vehicle_channel_sale_delete",
                idempotency_key=(
                    f"vehicle-channel:{channel.pk}:car:{car.pk}:sale-delete:"
                    f"{publication.revision}"
                ),
                target_message_id=publication.telegram_message_id,
                operation=TelegramOutboxMessage.Operation.DELETE_MESSAGE,
            )
            # A deleted post cannot be edited on sale reversal. Reset the live
            # identity so the reversal creates a fresh available-vehicle post.
            publication.telegram_message_id = None
            publication.content_mode = "message"
        else:
            body = (_vehicle_publication_body(car=car) + "\n\n⛔ وضعیت: فروخته‌شد")[:1024]
            operation = (
                TelegramOutboxMessage.Operation.EDIT_MEDIA_CAPTION
                if publication.content_mode == "caption"
                else TelegramOutboxMessage.Operation.EDIT_MESSAGE
            )
            outbox_message = queue_telegram_message(
                chat_id=channel.chat_id,
                body=body,
                message_type="vehicle_channel_sale_mark_sold",
                idempotency_key=(
                    f"vehicle-channel:{channel.pk}:car:{car.pk}:sale-mark:"
                    f"{publication.revision}"
                ),
                target_message_id=publication.telegram_message_id,
                operation=operation,
            )
    elif car.status == Car.Status.FOR_SALE:
        body = _vehicle_publication_body(car=car)
        operation = (
            TelegramOutboxMessage.Operation.EDIT_MEDIA_CAPTION
            if publication.content_mode == "caption"
            else TelegramOutboxMessage.Operation.EDIT_MESSAGE
        )
        outbox_message = queue_telegram_message(
            chat_id=channel.chat_id,
            body=body,
            message_type="vehicle_channel_sale_reversed",
            idempotency_key=(
                f"vehicle-channel:{channel.pk}:car:{car.pk}:sale-reversed:"
                f"{publication.revision}"
            ),
            target_message_id=publication.telegram_message_id,
            operation=operation,
        )
    else:
        return None

    publication.latest_outbox_message = outbox_message
    publication.save(
        update_fields=[
            "latest_outbox_message",
            "telegram_message_id",
            "content_mode",
            "revision",
            "updated_at",
        ]
    )
    return outbox_message


def _queue_unsent_vehicle_media(*, car, channel, excluded_refs=None):
    """Queue each gallery file once; Telegram file IDs prevent duplicates."""
    from cars.models import CarPhoto, CarVideo

    excluded_refs = {
        (item["type"], item["id"])
        for item in (excluded_refs or [])
    }

    for photo in CarPhoto.objects.filter(
        car=car,
        telegram_file_id__isnull=True,
        image__isnull=False,
    ).exclude(image=""):
        if ("car_photo", photo.pk) in excluded_refs:
            continue
        queue_telegram_message(
            chat_id=channel.chat_id,
            body="",
            message_type="vehicle_channel_photo",
            idempotency_key=f"vehicle-channel:{channel.pk}:photo:{photo.pk}",
            operation=TelegramOutboxMessage.Operation.SEND_PHOTO,
            media_object_type="car_photo",
            media_object_id=photo.pk,
        )

    for video in CarVideo.objects.filter(
        car=car,
        telegram_file_id__isnull=True,
        video__isnull=False,
    ).exclude(video=""):
        if ("car_video", video.pk) in excluded_refs:
            continue
        queue_telegram_message(
            chat_id=channel.chat_id,
            body=video.caption,
            message_type="vehicle_channel_video",
            idempotency_key=f"vehicle-channel:{channel.pk}:video:{video.pk}",
            operation=TelegramOutboxMessage.Operation.SEND_VIDEO,
            media_object_type="car_video",
            media_object_id=video.pk,
        )


def _outbox_media_refs(*, outbox_message):
    """Normalize an outbox item's local media references for duplicate avoidance."""
    if outbox_message.operation == TelegramOutboxMessage.Operation.SEND_MEDIA_GROUP:
        return list(outbox_message.media_object_refs or [])
    if outbox_message.operation in {
        TelegramOutboxMessage.Operation.SEND_PHOTO,
        TelegramOutboxMessage.Operation.SEND_VIDEO,
    } and outbox_message.media_object_type and outbox_message.media_object_id:
        return [{
            "type": outbox_message.media_object_type,
            "id": outbox_message.media_object_id,
        }]
    return []


@transaction.atomic
def update_telegram_integration_settings(*, actor, settings_data):
    """Persist non-secret Telegram controls after administrator authorization."""

    _require_system_administrator(actor=actor)
    settings_record, _ = TelegramIntegrationSettings.objects.select_for_update().get_or_create(
        pk=1
    )
    for field_name in (
        "inbound_mode",
        "staff_bot_enabled",
        "customer_notifications_enabled",
        "vehicle_channel_sync_enabled",
        "default_vehicle_channel",
        "sold_vehicle_publication_action",
    ):
        setattr(settings_record, field_name, settings_data[field_name])
    settings_record.updated_by = actor
    settings_record.full_clean()
    settings_record.save()
    return settings_record


def _clean_telegram_identifier(value, field_name):
    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field_name} تلگرام معتبر نیست.")

    # Private users are positive, while Telegram channel/group chat IDs are
    # conventionally negative (for example: -100...). Only zero is invalid.
    if normalized_value == 0:
        raise ValidationError(f"{field_name} تلگرام معتبر نیست.")

    return normalized_value


def _hash_staff_link_code(code):
    return salted_hmac(
        "integrations.telegram.staff-link-code",
        str(code),
    ).hexdigest()


def _hash_customer_activation_code(code):
    return salted_hmac(
        "integrations.telegram.customer-activation-code",
        str(code),
    ).hexdigest()


def _require_system_administrator(*, actor):
    require_active_internal_staff(actor=actor)

    if not actor.is_superuser:
        raise ValidationError(
            "فقط مدیر اصلی سیستم اجازهٔ مدیریت اتصال کارکنان به تلگرام را دارد."
        )


def _make_staff_link_code():
    # The raw code is returned once to the administrator and is never stored.
    return f"TGL-{secrets.token_urlsafe(18)}"


def _make_session_token():
    # Telegram callback_data has a 64-byte limit; this token remains well below it.
    return secrets.token_urlsafe(24)


def _make_customer_activation_code():
    # This is distinct from staff codes so /start can route safely by prefix.
    return f"TGC-{secrets.token_urlsafe(24)}"


def _require_customer_activation_issuer(*, actor):
    require_permission(
        actor=actor,
        permission="integrations.issue_customer_telegram_activation",
        error_message=(
            "شما اجازهٔ صدور کد فعال‌سازی ربات برای مشتری را ندارید."
        ),
    )


@transaction.atomic
def create_telegram_staff_link_code(*, staff_user, actor, ttl_minutes=None):
    """Issues one high-entropy, short-lived code for one internal staff user."""

    _require_system_administrator(actor=actor)

    if not staff_user.is_active or not staff_user.is_staff:
        raise ValidationError("فقط برای یک کارمند داخلی و فعال می‌توان کد اتصال ساخت.")

    ttl_minutes = (
        settings.TELEGRAM_LINK_CODE_TTL_MINUTES
        if ttl_minutes is None
        else int(ttl_minutes)
    )

    if ttl_minutes <= 0:
        raise ValidationError("مدت اعتبار کد اتصال باید بیشتر از صفر باشد.")

    now = timezone.now()

    # A new code invalidates outstanding unused codes for the same staff member.
    TelegramStaffLinkToken.objects.select_for_update().filter(
        user=staff_user,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(
        revoked_at=now,
        revoked_by=actor,
    )

    raw_code = _make_staff_link_code()
    link_token = TelegramStaffLinkToken.objects.create(
        user=staff_user,
        code_hash=_hash_staff_link_code(raw_code),
        created_by=actor,
        expires_at=now + timedelta(minutes=ttl_minutes),
    )

    return {
        "code": raw_code,
        "expires_at": link_token.expires_at,
        "token": link_token,
    }


@transaction.atomic
def revoke_pending_telegram_staff_link_codes(*, staff_user, actor):
    """Invalidate unused staff-link codes without retaining or exposing them.

    This is used when an internal account is deactivated.  The tokens remain
    as protected audit records, but cannot be used to establish a Telegram
    connection later.
    """

    _require_system_administrator(actor=actor)

    return TelegramStaffLinkToken.objects.select_for_update().filter(
        user=staff_user,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(
        revoked_at=timezone.now(),
        revoked_by=actor,
    )


@transaction.atomic
def revoke_telegram_staff_link(*, staff_link, actor, reason=""):
    """Revokes an active staff link while preserving its audit history."""

    _require_system_administrator(actor=actor)

    locked_link = TelegramStaffLink.objects.select_for_update().get(pk=staff_link.pk)

    if not locked_link.is_active:
        return locked_link

    locked_link.is_active = False
    locked_link.unlinked_at = timezone.now()
    locked_link.unlinked_by = actor
    locked_link.unlink_reason = str(reason or "").strip()
    locked_link.save(
        update_fields=[
            "is_active",
            "unlinked_at",
            "unlinked_by",
            "unlink_reason",
        ]
    )

    return locked_link


def link_staff_telegram_account(
    *,
    code,
    telegram_user_id,
    telegram_chat_id,
    telegram_username="",
    first_name="",
    last_name="",
):
    """Consumes a one-time code and records a verified private Telegram link."""

    normalized_user_id = _clean_telegram_identifier(
        telegram_user_id,
        "شناسهٔ کاربر",
    )
    normalized_chat_id = _clean_telegram_identifier(
        telegram_chat_id,
        "شناسهٔ چت",
    )
    normalized_code = str(code or "").strip()

    if not normalized_code:
        raise ValidationError("کد اتصال معتبر نیست یا منقضی شده است.")

    failure_message = ""
    staff_link = None

    # We deliberately raise validation errors *after* this transaction exits.
    # That way an attempted use of an expired/revoked code increments the audit
    # counter instead of being rolled back together with the error.
    with transaction.atomic():
        try:
            link_token = (
                TelegramStaffLinkToken.objects.select_for_update()
                .select_related("user")
                .get(code_hash=_hash_staff_link_code(normalized_code))
            )
        except TelegramStaffLinkToken.DoesNotExist:
            failure_message = "کد اتصال معتبر نیست یا منقضی شده است."
        else:
            link_token.attempt_count += 1
            link_token.save(update_fields=["attempt_count"])
            now = timezone.now()

            if (
                link_token.used_at is not None
                or link_token.revoked_at is not None
                or link_token.expires_at <= now
            ):
                failure_message = "کد اتصال معتبر نیست یا منقضی شده است."
            else:
                try:
                    require_active_internal_staff(actor=link_token.user)
                except ValidationError:
                    failure_message = "این حساب کارمند برای اتصال به تلگرام فعال نیست."

            if not failure_message:
                conflicting_link = (
                    TelegramStaffLink.objects.select_for_update()
                    .filter(is_active=True)
                    .filter(
                        Q(telegram_user_id=normalized_user_id)
                        | Q(telegram_chat_id=normalized_chat_id)
                    )
                    .exclude(user=link_token.user)
                    .first()
                )

                if conflicting_link is not None:
                    failure_message = (
                        "این حساب تلگرام قبلاً به کارمند دیگری متصل شده است."
                    )

            if not failure_message:
                # Relinking the same employee is deliberate: old records remain auditable.
                TelegramStaffLink.objects.select_for_update().filter(
                    user=link_token.user,
                    is_active=True,
                ).update(
                    is_active=False,
                    unlinked_at=now,
                    unlinked_by=link_token.created_by,
                    unlink_reason="اتصال جدید تلگرام برای این کارمند ثبت شد.",
                )

                staff_link = TelegramStaffLink.objects.create(
                    user=link_token.user,
                    telegram_user_id=normalized_user_id,
                    telegram_chat_id=normalized_chat_id,
                    telegram_username=str(telegram_username or "")[:255],
                    first_name=str(first_name or "")[:255],
                    last_name=str(last_name or "")[:255],
                    last_seen_at=now,
                )

                link_token.used_at = now
                link_token.used_telegram_user_id = normalized_user_id
                link_token.save(
                    update_fields=[
                        "used_at",
                        "used_telegram_user_id",
                    ]
                )

    if failure_message:
        raise ValidationError(failure_message)

    return staff_link


def get_active_telegram_staff_link(*, telegram_user_id, telegram_chat_id, touch=True):
    """Returns the exact active staff link for a private Telegram identity."""

    normalized_user_id = _clean_telegram_identifier(
        telegram_user_id,
        "شناسهٔ کاربر",
    )
    normalized_chat_id = _clean_telegram_identifier(
        telegram_chat_id,
        "شناسهٔ چت",
    )

    staff_link = (
        TelegramStaffLink.objects.select_related("user")
        .filter(
            telegram_user_id=normalized_user_id,
            telegram_chat_id=normalized_chat_id,
            is_active=True,
        )
        .first()
    )

    if staff_link is None:
        return None

    try:
        require_active_internal_staff(actor=staff_link.user)
    except ValidationError:
        return None

    if touch:
        TelegramStaffLink.objects.filter(pk=staff_link.pk).update(
            last_seen_at=timezone.now()
        )
        staff_link.last_seen_at = timezone.now()

    return staff_link


def _get_customer_activation_car(*, car_id):
    """Loads a sale that is eligible for verified customer tracking."""

    from cars.models import Car

    try:
        car = Car.objects.select_for_update().get(pk=car_id)
    except Car.DoesNotExist:
        raise ValidationError("خودروی موردنظر پیدا نشد.")

    if car.is_deleted:
        raise ValidationError("برای خودروی بایگانی‌شده نمی‌توان کد فعال‌سازی صادر کرد.")

    if car.customer_id is None or car.status not in {
        Car.Status.SOLD,
        Car.Status.IN_TRANSIT,
        Car.Status.DELIVERED,
    }:
        raise ValidationError(
            "کد فعال‌سازی فقط برای خودروی فروخته‌شدهٔ دارای مشتری صادر می‌شود."
        )

    return car


@transaction.atomic
def create_customer_telegram_activation_code(
    *,
    car,
    actor,
    ttl_days=None,
    enforce_issue_permission=True,
):
    """
    Issues one customer activation code and invalidates older unused codes.

    A sale workflow may call this with ``enforce_issue_permission=False`` after
    it has already verified the actor's ``cars.sell_vehicle`` permission.  A
    manual reissue always requires the dedicated integration permission.
    """

    if enforce_issue_permission:
        _require_customer_activation_issuer(actor=actor)

    locked_car = _get_customer_activation_car(car_id=car.pk)

    ttl_days = (
        settings.TELEGRAM_CUSTOMER_ACTIVATION_CODE_TTL_DAYS
        if ttl_days is None
        else int(ttl_days)
    )

    if ttl_days <= 0:
        raise ValidationError("مدت اعتبار کد فعال‌سازی باید بیشتر از صفر باشد.")

    now = timezone.now()

    # Only one outstanding code should exist for a sale at a time.
    TelegramCustomerActivationToken.objects.select_for_update().filter(
        car=locked_car,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(
        revoked_at=now,
        revoked_by=actor,
    )

    raw_code = _make_customer_activation_code()
    token = TelegramCustomerActivationToken.objects.create(
        car=locked_car,
        customer=locked_car.customer,
        code_hash=_hash_customer_activation_code(raw_code),
        created_by=actor,
        expires_at=now + timedelta(days=ttl_days),
    )

    return {
        "code": raw_code,
        "expires_at": token.expires_at,
        "token": token,
    }


def _get_active_customer_subscription(
    *,
    telegram_user_id,
    telegram_chat_id,
    touch=True,
):
    """Returns all active subscriptions for one verified private identity."""

    normalized_user_id = _clean_telegram_identifier(
        telegram_user_id,
        "شناسهٔ کاربر",
    )
    normalized_chat_id = _clean_telegram_identifier(
        telegram_chat_id,
        "شناسهٔ چت",
    )

    subscriptions = list(
        CustomerTelegramSubscription.objects.select_related("car", "customer")
        .filter(
            telegram_user_id=normalized_user_id,
            telegram_chat_id=normalized_chat_id,
            is_active=True,
        )
        .order_by("-subscribed_at")
    )

    if touch and subscriptions:
        now = timezone.now()
        CustomerTelegramSubscription.objects.filter(
            pk__in=[subscription.pk for subscription in subscriptions]
        ).update(last_seen_at=now)
        for subscription in subscriptions:
            subscription.last_seen_at = now

    return subscriptions


def get_active_customer_telegram_subscriptions(
    *,
    telegram_user_id,
    telegram_chat_id,
    touch=True,
):
    """Public wrapper used by the Telegram adapter and no other identity type."""

    return _get_active_customer_subscription(
        telegram_user_id=telegram_user_id,
        telegram_chat_id=telegram_chat_id,
        touch=touch,
    )


def activate_customer_telegram_tracking(
    *,
    code,
    telegram_user_id,
    telegram_chat_id,
    telegram_username="",
    first_name="",
    last_name="",
):
    """Consumes a customer code and creates a verified tracking subscription."""

    normalized_user_id = _clean_telegram_identifier(
        telegram_user_id,
        "شناسهٔ کاربر",
    )
    normalized_chat_id = _clean_telegram_identifier(
        telegram_chat_id,
        "شناسهٔ چت",
    )
    normalized_code = str(code or "").strip()

    if not normalized_code:
        raise ValidationError("کد فعال‌سازی معتبر نیست یا منقضی شده است.")

    failure_message = ""
    subscription = None

    # Like staff-link codes, invalid uses increment an audit counter and are not
    # rolled back together with the generic validation response.
    with transaction.atomic():
        try:
            token = (
                TelegramCustomerActivationToken.objects.select_for_update()
                .select_related("car", "customer")
                .get(code_hash=_hash_customer_activation_code(normalized_code))
            )
        except TelegramCustomerActivationToken.DoesNotExist:
            failure_message = "کد فعال‌سازی معتبر نیست یا منقضی شده است."
        else:
            token.attempt_count += 1
            token.save(update_fields=["attempt_count"])
            now = timezone.now()

            if (
                token.used_at is not None
                or token.revoked_at is not None
                or token.expires_at <= now
            ):
                failure_message = "کد فعال‌سازی معتبر نیست یا منقضی شده است."
            else:
                from cars.models import Car

                car = Car.objects.select_for_update().get(pk=token.car_id)
                if (
                    car.is_deleted
                    or car.customer_id != token.customer_id
                    or car.status
                    not in {
                        Car.Status.SOLD,
                        Car.Status.IN_TRANSIT,
                        Car.Status.DELIVERED,
                    }
                ):
                    failure_message = "کد فعال‌سازی معتبر نیست یا منقضی شده است."

            if not failure_message:
                # A newly issued valid code is an explicit authorization to move
                # notifications to a new private Telegram account.  The former
                # subscription remains as audit history and receives no more data.
                CustomerTelegramSubscription.objects.select_for_update().filter(
                    car_id=token.car_id,
                    is_active=True,
                ).update(
                    is_active=False,
                    unsubscribed_at=now,
                    unsubscribe_reason="با فعال‌سازی جدید جایگزین شد.",
                )

                subscription = CustomerTelegramSubscription.objects.create(
                    car_id=token.car_id,
                    customer_id=token.customer_id,
                    telegram_user_id=normalized_user_id,
                    telegram_chat_id=normalized_chat_id,
                    telegram_username=str(telegram_username or "")[:255],
                    first_name=str(first_name or "")[:255],
                    last_name=str(last_name or "")[:255],
                    last_seen_at=now,
                )

                token.used_at = now
                token.used_telegram_user_id = normalized_user_id
                token.save(
                    update_fields=[
                        "used_at",
                        "used_telegram_user_id",
                    ]
                )

    if failure_message:
        raise ValidationError(failure_message)

    return subscription


@transaction.atomic
def unsubscribe_customer_telegram_tracking(
    *,
    tracking_code,
    telegram_user_id,
    telegram_chat_id,
):
    """Stops notifications for exactly one vehicle in the caller's private chat."""

    normalized_code = str(tracking_code or "").strip()
    if not normalized_code:
        raise ValidationError("کد رهگیری را برای توقف اعلان وارد کنید.")

    normalized_user_id = _clean_telegram_identifier(
        telegram_user_id,
        "شناسهٔ کاربر",
    )
    normalized_chat_id = _clean_telegram_identifier(
        telegram_chat_id,
        "شناسهٔ چت",
    )

    subscription = (
        CustomerTelegramSubscription.objects.select_for_update()
        .select_related("car")
        .filter(
            car__tracking_code=normalized_code,
            telegram_user_id=normalized_user_id,
            telegram_chat_id=normalized_chat_id,
            is_active=True,
        )
        .first()
    )

    if subscription is None:
        raise ValidationError("اشتراک فعال برای این کد رهگیری پیدا نشد.")

    subscription.is_active = False
    subscription.unsubscribed_at = timezone.now()
    subscription.unsubscribe_reason = "لغو توسط مشتری در ربات تلگرام."
    subscription.save(
        update_fields=[
            "is_active",
            "unsubscribed_at",
            "unsubscribe_reason",
        ]
    )

    return subscription


@transaction.atomic
def revoke_customer_telegram_subscription(*, subscription, actor, reason=""):
    """System-administrator safety operation for a verified customer link."""

    _require_system_administrator(actor=actor)

    locked_subscription = CustomerTelegramSubscription.objects.select_for_update().get(
        pk=subscription.pk
    )

    if not locked_subscription.is_active:
        return locked_subscription

    locked_subscription.is_active = False
    locked_subscription.unsubscribed_at = timezone.now()
    locked_subscription.unsubscribe_reason = str(reason or "").strip() or (
        "لغو توسط مدیر اصلی سیستم."
    )
    locked_subscription.save(
        update_fields=[
            "is_active",
            "unsubscribed_at",
            "unsubscribe_reason",
        ]
    )

    return locked_subscription


def is_telegram_tracking_lookup_allowed(*, telegram_user_id, telegram_chat_id):
    """Rate-limits bot lookups by Telegram identity rather than Telegram's IP."""

    attempt_limit = int(settings.TELEGRAM_TRACKING_RATE_LIMIT_ATTEMPTS)
    window_seconds = int(settings.TELEGRAM_TRACKING_RATE_LIMIT_WINDOW_SECONDS)

    if attempt_limit <= 0 or window_seconds <= 0:
        return True

    try:
        normalized_user_id = _clean_telegram_identifier(
            telegram_user_id,
            "شناسهٔ کاربر",
        )
        normalized_chat_id = _clean_telegram_identifier(
            telegram_chat_id,
            "شناسهٔ چت",
        )
    except ValidationError:
        return False

    cache_key = (
        "telegram-customer-tracking-rate-limit:"
        f"{normalized_user_id}:{normalized_chat_id}"
    )

    if cache.add(cache_key, 1, timeout=window_seconds):
        return True

    try:
        attempt_count = cache.incr(cache_key)
    except ValueError:
        # A key can expire between add and incr.
        cache.set(cache_key, 1, timeout=window_seconds)
        return True

    return attempt_count <= attempt_limit


def get_customer_bot_tracking_data(*, tracking_code):
    """Returns the shared safe lookup data and records a successful bot lookup."""

    from customers.models import SearchLog
    from customers.services import record_successful_tracking_lookup
    from tracking.services import get_public_tracking_data

    tracking_data = get_public_tracking_data(tracking_code=tracking_code)

    try:
        record_successful_tracking_lookup(
            tracking_code=tracking_data["tracking_code"],
            source=SearchLog.Source.BOT,
        )
    except Exception:
        # Lookup availability must not depend on a non-critical audit write.
        logger.exception("Could not record a successful Telegram tracking lookup.")

    return tracking_data


def _get_notification_snapshot(*, tracking_event):
    """Builds a resilient, public-safe snapshot for an outbound update message."""

    from cars.models import Car
    from tracking.services import calculate_remaining_eta_days

    car = Car.objects.select_related("current_stage").get(pk=tracking_event.car_id)

    try:
        remaining_eta_days = calculate_remaining_eta_days(car)
    except ValidationError:
        # A stage may be in the middle of an administrative archive operation.
        # The notice remains useful without an ETA; live lookup recalculates later.
        remaining_eta_days = None

    return {
        "tracking_code": car.tracking_code,
        "vehicle_title": car.title,
        "current_stage_name": (
            car.current_stage.name if car.current_stage is not None else None
        ),
        "remaining_eta_days": remaining_eta_days,
        "event_type": tracking_event.event_type,
        "previous_stage_name": (
            tracking_event.previous_stage.name
            if tracking_event.previous_stage_id
            else None
        ),
        "new_stage_name": (
            tracking_event.new_stage.name if tracking_event.new_stage_id else None
        ),
    }


def queue_customer_tracking_notifications_for_event(*, tracking_event):
    """
    Explicitly creates notification intents for a customer-visible event.

    This function is called by the tracking service in the same transaction as
    the immutable event.  The durable Outbox task is still scheduled only on
    successful database commit.
    """

    customer_visible_events = {
        "stage_confirmed",
        "stage_completed",
        "stage_corrected",
        "stage_skipped",
        "stage_archived",
    }

    if tracking_event.event_type not in customer_visible_events:
        return []

    if not get_telegram_integration_settings().customer_notifications_enabled:
        return []

    subscriptions = list(
        CustomerTelegramSubscription.objects.select_related("car")
        .filter(
            car_id=tracking_event.car_id,
            is_active=True,
        )
        .order_by("pk")
    )

    if not subscriptions:
        return []

    from .telegram.messages import customer_tracking_notification_text

    snapshot = _get_notification_snapshot(tracking_event=tracking_event)
    notifications = []

    for subscription in subscriptions:
        notification, created = CustomerTrackingNotification.objects.get_or_create(
            tracking_event=tracking_event,
            subscription=subscription,
        )

        if created:
            outbox_message = queue_telegram_message(
                chat_id=subscription.telegram_chat_id,
                body=customer_tracking_notification_text(snapshot=snapshot),
                message_type="customer_tracking_notification",
                idempotency_key=(
                    f"tracking-event:{tracking_event.pk}:"
                    f"subscription:{subscription.pk}"
                ),
                customer_subscription=subscription,
            )
            notification.outbox_message = outbox_message
            notification.save(update_fields=["outbox_message"])

        notifications.append(notification)

    return notifications


@transaction.atomic
def create_telegram_stage_confirmation_session(*, staff_link, tracking_code):
    """Creates a staff-bound review step before a Telegram stage confirmation."""

    active_link = TelegramStaffLink.objects.select_for_update().select_related(
        "user"
    ).get(pk=staff_link.pk)

    if not active_link.is_active:
        raise ValidationError("اتصال تلگرام این کارمند فعال نیست.")

    try:
        require_active_internal_staff(actor=active_link.user)
    except ValidationError:
        raise ValidationError("حساب کارمند برای تأیید مرحله فعال نیست.")

    # Local import keeps the integration boundary explicit and avoids startup coupling.
    from tracking.services import get_stage_confirmation_preview

    preview = get_stage_confirmation_preview(
        tracking_code=tracking_code,
        staff=active_link.user,
    )

    return TelegramStageConfirmationSession.objects.create(
        public_token=_make_session_token(),
        staff_link=active_link,
        car=preview["car"],
        stage=preview["stage"],
        expires_at=timezone.now()
        + timedelta(minutes=settings.TELEGRAM_CONFIRMATION_SESSION_TTL_MINUTES),
    )


def _get_staff_session(*, staff_link, public_token):
    try:
        session = (
            TelegramStageConfirmationSession.objects.select_for_update()
            .select_related("staff_link__user", "car", "stage")
            .get(public_token=str(public_token or "").strip())
        )
    except TelegramStageConfirmationSession.DoesNotExist:
        raise ValidationError("درخواست تأیید پیدا نشد یا دیگر معتبر نیست.")

    if session.staff_link_id != staff_link.pk:
        raise ValidationError("این درخواست تأیید متعلق به شما نیست.")

    if session.status == TelegramStageConfirmationSession.Status.PENDING:
        if session.expires_at <= timezone.now():
            session.status = TelegramStageConfirmationSession.Status.EXPIRED
            session.save(update_fields=["status"])
            raise ValidationError("مهلت تأیید این درخواست تمام شده است.")

    return session


@transaction.atomic
def cancel_telegram_stage_confirmation_session(*, staff_link, public_token):
    """Cancels a pending preview without changing tracking state."""

    session = _get_staff_session(
        staff_link=staff_link,
        public_token=public_token,
    )

    if session.status == TelegramStageConfirmationSession.Status.CANCELLED:
        return session

    if session.status != TelegramStageConfirmationSession.Status.PENDING:
        raise ValidationError("این درخواست دیگر قابل لغو نیست.")

    session.status = TelegramStageConfirmationSession.Status.CANCELLED
    session.cancelled_at = timezone.now()
    session.save(update_fields=["status", "cancelled_at"])

    return session


@transaction.atomic
def confirm_telegram_stage_confirmation_session(*, staff_link, public_token):
    """Runs the final shared tracking service for a reviewed Telegram action."""

    session = _get_staff_session(
        staff_link=staff_link,
        public_token=public_token,
    )

    if session.status == TelegramStageConfirmationSession.Status.CONFIRMED:
        return {
            "session": session,
            "progress": None,
            "already_confirmed": True,
        }

    if session.status != TelegramStageConfirmationSession.Status.PENDING:
        raise ValidationError("این درخواست دیگر قابل تأیید نیست.")

    from tracking.models import TrackingEvent
    from tracking.services import confirm_stage

    try:
        progress = confirm_stage(
            car=session.car,
            stage=session.stage,
            staff=session.staff_link.user,
            source=TrackingEvent.Source.TELEGRAM_BOT,
        )
    except ValidationError:
        # Do not persist potentially sensitive internal details in the bot audit table.
        session.status = TelegramStageConfirmationSession.Status.FAILED
        session.failure_reason = "اعتبارسنجی وضعیت یا دسترسی مرحله ناموفق بود."
        session.save(update_fields=["status", "failure_reason"])
        raise

    session.status = TelegramStageConfirmationSession.Status.CONFIRMED
    session.confirmed_at = timezone.now()
    session.save(update_fields=["status", "confirmed_at"])

    return {
        "session": session,
        "progress": progress,
        "already_confirmed": False,
    }


def _schedule_outbox_delivery(outbox_id):
    """Best-effort enqueue; the durable outbox remains recoverable if this fails."""

    try:
        from .tasks import deliver_telegram_outbox_message_task

        deliver_telegram_outbox_message_task.delay(outbox_id)
    except Exception:
        # No token, user input, or Telegram payload is emitted to logs here.
        logger.exception("Unable to enqueue Telegram outbox message id=%s.", outbox_id)


def queue_telegram_message(
    *,
    chat_id,
    body,
    message_type,
    idempotency_key,
    reply_markup=None,
    reply_to_message_id=None,
    target_message_id=None,
    operation=TelegramOutboxMessage.Operation.SEND_MESSAGE,
    media_object_type="",
    media_object_id=None,
    media_object_refs=None,
    inbound_update=None,
    staff_link=None,
    customer_subscription=None,
):
    """Creates one durable outbound message and schedules its delivery after commit."""

    outbox_message, created = TelegramOutboxMessage.objects.get_or_create(
        idempotency_key=str(idempotency_key),
        defaults={
            "operation": operation,
            "chat_id": _clean_telegram_identifier(chat_id, "شناسهٔ چت"),
            "body": str(body or ""),
            "reply_markup": reply_markup,
            "reply_to_message_id": reply_to_message_id,
            "target_message_id": target_message_id,
            "media_object_type": str(media_object_type or ""),
            "media_object_id": media_object_id,
            "media_object_refs": media_object_refs,
            "message_type": str(message_type),
            "inbound_update": inbound_update,
            "staff_link": staff_link,
            "customer_subscription": customer_subscription,
        },
    )

    if created:
        transaction.on_commit(
            lambda outbox_id=outbox_message.pk: _schedule_outbox_delivery(outbox_id)
        )

    return outbox_message


def queue_telegram_callback_ack(
    *,
    callback_query_id,
    body,
    idempotency_key,
    inbound_update=None,
    staff_link=None,
):
    """Queues the callback acknowledgement separately from the visible reply."""

    outbox_message, created = TelegramOutboxMessage.objects.get_or_create(
        idempotency_key=str(idempotency_key),
        defaults={
            "operation": TelegramOutboxMessage.Operation.ANSWER_CALLBACK,
            "callback_query_id": str(callback_query_id or ""),
            "body": str(body or ""),
            "message_type": "callback_ack",
            "inbound_update": inbound_update,
            "staff_link": staff_link,
        },
    )

    if created:
        transaction.on_commit(
            lambda outbox_id=outbox_message.pk: _schedule_outbox_delivery(outbox_id)
        )

    return outbox_message


def _parse_command(text):
    normalized_text = str(text or "").strip()

    if not normalized_text.startswith("/"):
        return "", ""

    command_with_optional_bot, _, arguments = normalized_text.partition(" ")
    command = command_with_optional_bot.split("@", 1)[0].lower()

    return command, arguments.strip()


def parse_telegram_update(update):
    """Extracts only the small, non-secret subset needed to process an update."""

    if not isinstance(update, dict):
        raise ValidationError("دادهٔ دریافتی از تلگرام معتبر نیست.")

    try:
        update_id = int(update["update_id"])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("شناسهٔ به‌روزرسانی تلگرام معتبر نیست.")

    message = update.get("message")
    if isinstance(message, dict):
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        command_name, command_argument = _parse_command(message.get("text"))

        return {
            "telegram_update_id": update_id,
            "update_type": TelegramInboundUpdate.UpdateType.MESSAGE,
            "telegram_user_id": sender.get("id"),
            "telegram_chat_id": chat.get("id"),
            "telegram_message_id": message.get("message_id"),
            "chat_type": chat.get("type", ""),
            "telegram_username": sender.get("username", ""),
            "first_name": sender.get("first_name", ""),
            "last_name": sender.get("last_name", ""),
            "command_name": command_name,
            "command_argument": command_argument,
            "callback_query_id": "",
            "callback_data": "",
        }

    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        callback_message = callback_query.get("message") or {}
        sender = callback_query.get("from") or {}
        chat = callback_message.get("chat") or {}

        return {
            "telegram_update_id": update_id,
            "update_type": TelegramInboundUpdate.UpdateType.CALLBACK_QUERY,
            "telegram_user_id": sender.get("id"),
            "telegram_chat_id": chat.get("id"),
            "telegram_message_id": callback_message.get("message_id"),
            "chat_type": chat.get("type", ""),
            "telegram_username": sender.get("username", ""),
            "first_name": sender.get("first_name", ""),
            "last_name": sender.get("last_name", ""),
            "command_name": "",
            "command_argument": "",
            "callback_query_id": callback_query.get("id", ""),
            "callback_data": callback_query.get("data", ""),
        }

    return {
        "telegram_update_id": update_id,
        "update_type": TelegramInboundUpdate.UpdateType.UNSUPPORTED,
        "telegram_user_id": None,
        "telegram_chat_id": None,
        "telegram_message_id": None,
        "chat_type": "",
        "telegram_username": "",
        "first_name": "",
        "last_name": "",
        "command_name": "",
        "command_argument": "",
        "callback_query_id": "",
        "callback_data": "",
    }


def _create_or_get_inbound_update(parsed):
    defaults = {
        "telegram_user_id": parsed["telegram_user_id"],
        "telegram_chat_id": parsed["telegram_chat_id"],
        "telegram_message_id": parsed["telegram_message_id"],
        "update_type": parsed["update_type"],
        "command_name": parsed["command_name"][:60],
    }

    try:
        return TelegramInboundUpdate.objects.get_or_create(
            telegram_update_id=parsed["telegram_update_id"],
            defaults=defaults,
        )
    except IntegrityError:
        # Concurrent webhook/poll delivery can race on Telegram's update ID.
        return (
            TelegramInboundUpdate.objects.get(
                telegram_update_id=parsed["telegram_update_id"]
            ),
            False,
        )


def _record_failed_inbound_update(parsed):
    TelegramInboundUpdate.objects.update_or_create(
        telegram_update_id=parsed["telegram_update_id"],
        defaults={
            "telegram_user_id": parsed["telegram_user_id"],
            "telegram_chat_id": parsed["telegram_chat_id"],
            "telegram_message_id": parsed["telegram_message_id"],
            "update_type": parsed["update_type"],
            "command_name": parsed["command_name"][:60],
            "status": TelegramInboundUpdate.Status.FAILED,
            "error_summary": "پردازش داخلی پیام تلگرام ناموفق بود.",
        },
    )


def ingest_and_process_telegram_update(*, update):
    """Idempotently processes one webhook or polling update without storing raw input."""

    parsed = parse_telegram_update(update)

    try:
        with transaction.atomic():
            inbound_update, created = _create_or_get_inbound_update(parsed)

            if (
                not created
                and inbound_update.status == TelegramInboundUpdate.Status.PROCESSED
            ):
                return {
                    "inbound_update": inbound_update,
                    "duplicate": True,
                }

            staff_link = None
            customer_subscriptions = []
            if (
                parsed["telegram_user_id"] is not None
                and parsed["telegram_chat_id"] is not None
            ):
                try:
                    staff_link = get_active_telegram_staff_link(
                        telegram_user_id=parsed["telegram_user_id"],
                        telegram_chat_id=parsed["telegram_chat_id"],
                    )
                except ValidationError:
                    staff_link = None

                try:
                    customer_subscriptions = get_active_customer_telegram_subscriptions(
                        telegram_user_id=parsed["telegram_user_id"],
                        telegram_chat_id=parsed["telegram_chat_id"],
                    )
                except ValidationError:
                    customer_subscriptions = []

            if staff_link is not None:
                inbound_update.staff_link = staff_link

            customer_subscription = (
                customer_subscriptions[0] if customer_subscriptions else None
            )
            if customer_subscription is not None:
                inbound_update.customer_subscription = customer_subscription

            if staff_link is not None or customer_subscription is not None:
                inbound_update.save(
                    update_fields=["staff_link", "customer_subscription"]
                )

            # The adapter handles messages, while every domain write remains in a service.
            from .telegram.handlers import handle_telegram_inbound_update

            handle_telegram_inbound_update(
                inbound_update=inbound_update,
                parsed=parsed,
                staff_link=staff_link,
                customer_subscription=customer_subscription,
            )

            inbound_update.status = TelegramInboundUpdate.Status.PROCESSED
            inbound_update.error_summary = ""
            inbound_update.processed_at = timezone.now()
            inbound_update.save(
                update_fields=[
                    "status",
                    "error_summary",
                    "processed_at",
                    "staff_link",
                    "customer_subscription",
                ]
            )

            return {
                "inbound_update": inbound_update,
                "duplicate": False,
            }
    except Exception:
        # The log receives only the durable Telegram update ID, never command text.
        logger.exception(
            "Telegram inbound processing failed for update id=%s.",
            parsed["telegram_update_id"],
        )
        _record_failed_inbound_update(parsed)
        raise


def _claim_telegram_outbox_message(*, outbox_id):
    stale_before = timezone.now() - timedelta(
        seconds=getattr(settings, "TELEGRAM_OUTBOX_SENDING_TIMEOUT_SECONDS", 300)
    )

    with transaction.atomic():
        outbox_message = TelegramOutboxMessage.objects.select_for_update().get(pk=outbox_id)

        if outbox_message.status in {
            TelegramOutboxMessage.Status.SENT,
            TelegramOutboxMessage.Status.FAILED,
        }:
            return None

        if (
            outbox_message.status == TelegramOutboxMessage.Status.RETRY
            and outbox_message.next_attempt_at is not None
            and outbox_message.next_attempt_at > timezone.now()
        ):
            return None

        if (
            outbox_message.status == TelegramOutboxMessage.Status.SENDING
            and outbox_message.delivery_started_at is not None
            and outbox_message.delivery_started_at > stale_before
        ):
            return None

        outbox_message.status = TelegramOutboxMessage.Status.SENDING
        outbox_message.attempt_count += 1
        outbox_message.delivery_started_at = timezone.now()
        outbox_message.save(
            update_fields=[
                "status",
                "attempt_count",
                "delivery_started_at",
            ]
        )

        return outbox_message


def _retry_delay_seconds(attempt_count):
    return min(60 * (2 ** max(attempt_count - 1, 0)), 3600)


def _record_outbox_success(*, outbox_id, telegram_result):
    with transaction.atomic():
        outbox_message = TelegramOutboxMessage.objects.select_for_update().get(pk=outbox_id)

        if outbox_message.status != TelegramOutboxMessage.Status.SENDING:
            return {"outcome": "superseded"}

        message_id = None
        if isinstance(telegram_result, dict):
            message_id = telegram_result.get("message_id")
        elif isinstance(telegram_result, list) and telegram_result:
            first_result = telegram_result[0]
            if isinstance(first_result, dict):
                message_id = first_result.get("message_id")

        outbox_message.status = TelegramOutboxMessage.Status.SENT
        outbox_message.sent_at = timezone.now()
        outbox_message.next_attempt_at = None
        outbox_message.delivery_started_at = None
        outbox_message.telegram_message_id = message_id
        outbox_message.last_error_summary = ""
        outbox_message.save(
            update_fields=[
                "status",
                "sent_at",
                "next_attempt_at",
                "delivery_started_at",
                "telegram_message_id",
                "last_error_summary",
            ]
        )

        publication = (
            TelegramVehiclePublication.objects.select_for_update()
            .select_related("car", "channel")
            .filter(latest_outbox_message=outbox_message)
            .first()
        )
        if publication is not None:
            if outbox_message.operation in {
                TelegramOutboxMessage.Operation.SEND_MESSAGE,
                TelegramOutboxMessage.Operation.SEND_PHOTO,
                TelegramOutboxMessage.Operation.SEND_VIDEO,
                TelegramOutboxMessage.Operation.SEND_MEDIA_GROUP,
            }:
                publication.telegram_message_id = message_id
                publication.content_mode = (
                    "caption"
                    if outbox_message.operation
                    in {
                        TelegramOutboxMessage.Operation.SEND_PHOTO,
                        TelegramOutboxMessage.Operation.SEND_VIDEO,
                        TelegramOutboxMessage.Operation.SEND_MEDIA_GROUP,
                    }
                    else "message"
                )
            publication.last_synced_at = timezone.now()
            publication.save(
                update_fields=[
                    "telegram_message_id",
                    "content_mode",
                    "last_synced_at",
                    "updated_at",
                ]
            )

            if (
                outbox_message.message_type == "vehicle_channel_media_republish"
                and outbox_message.target_message_id is not None
                and message_id is not None
            ):
                replacement_refs = {
                    (item["type"], item["id"])
                    for item in _outbox_media_refs(outbox_message=outbox_message)
                }
                obsolete_message_ids = {outbox_message.target_message_id}
                legacy_media_messages = TelegramOutboxMessage.objects.filter(
                    chat_id=publication.channel.chat_id,
                    status=TelegramOutboxMessage.Status.SENT,
                    operation__in={
                        TelegramOutboxMessage.Operation.SEND_PHOTO,
                        TelegramOutboxMessage.Operation.SEND_VIDEO,
                    },
                    telegram_message_id__isnull=False,
                ).exclude(pk=outbox_message.pk)
                for legacy_message in legacy_media_messages:
                    legacy_ref = (
                        legacy_message.media_object_type,
                        legacy_message.media_object_id,
                    )
                    if legacy_ref in replacement_refs:
                        obsolete_message_ids.add(legacy_message.telegram_message_id)

                for obsolete_message_id in obsolete_message_ids:
                    if obsolete_message_id == message_id:
                        continue
                    queue_telegram_message(
                        chat_id=publication.channel.chat_id,
                        body="",
                        message_type="vehicle_channel_remove_legacy_post",
                        idempotency_key=(
                            f"vehicle-channel:{publication.channel_id}:car:{publication.car_id}:"
                            f"replacement:{outbox_message.pk}:delete:{obsolete_message_id}"
                        ),
                        target_message_id=obsolete_message_id,
                        operation=TelegramOutboxMessage.Operation.DELETE_MESSAGE,
                    )

            if publication.telegram_message_id is not None:
                channel_message_ids = dict(publication.car.channel_message_ids or {})
                channel_message_ids[str(publication.channel_id)] = publication.telegram_message_id
                publication.car.channel_message_ids = channel_message_ids
                publication.car.save(update_fields=["channel_message_ids"])

        if outbox_message.operation in {
            TelegramOutboxMessage.Operation.SEND_PHOTO,
            TelegramOutboxMessage.Operation.SEND_VIDEO,
            TelegramOutboxMessage.Operation.SEND_MEDIA_GROUP,
        }:
            _store_telegram_media_file_ids(
                outbox_message=outbox_message,
                telegram_result=telegram_result,
            )

        return {"outcome": "sent"}


def _store_telegram_media_file_ids(*, outbox_message, telegram_result):
    """Cache Telegram's returned file ID so an existing file is not resent."""
    results = telegram_result if isinstance(telegram_result, list) else [telegram_result]
    for reference, result in zip(_outbox_media_refs(outbox_message=outbox_message), results):
        _store_telegram_media_file_id(reference=reference, telegram_result=result)


def _store_telegram_media_file_id(*, reference, telegram_result):
    from cars.models import CarPhoto, CarVideo

    if reference["type"] == "car_photo":
        photo = CarPhoto.objects.select_for_update().filter(pk=reference["id"]).first()
        photos = telegram_result.get("photo", []) if isinstance(telegram_result, dict) else []
        file_id = photos[-1].get("file_id") if photos else None
        if photo is not None and file_id:
            photo.telegram_file_id = str(file_id)
            photo.save(update_fields=["telegram_file_id"])
    elif reference["type"] == "car_video":
        video = CarVideo.objects.select_for_update().filter(pk=reference["id"]).first()
        payload = telegram_result.get("video", {}) if isinstance(telegram_result, dict) else {}
        file_id = payload.get("file_id") if isinstance(payload, dict) else None
        if video is not None and file_id:
            video.telegram_file_id = str(file_id)
            video.save(update_fields=["telegram_file_id"])


def _load_outbox_vehicle_media(*, outbox_message):
    """Read one queued local file only when the Worker is ready to send it."""
    return _load_vehicle_media_reference(
        media_object_type=outbox_message.media_object_type,
        media_object_id=outbox_message.media_object_id,
    )


def _load_vehicle_media_reference(*, media_object_type, media_object_id):
    """Load one local gallery file without modifying its website source file."""
    from cars.models import CarPhoto, CarVideo
    from .telegram.gateway import TelegramGatewayPermanentError

    if media_object_type == "car_photo":
        item = CarPhoto.objects.filter(pk=media_object_id).first()
        file_field = item.image if item is not None else None
    elif media_object_type == "car_video":
        item = CarVideo.objects.filter(pk=media_object_id).first()
        file_field = item.video if item is not None else None
    else:
        item = None
        file_field = None

    if item is None or not file_field:
        raise TelegramGatewayPermanentError("Queued vehicle media no longer exists.")

    try:
        with file_field.open("rb") as media_file:
            file_data = media_file.read()
    except Exception as error:
        raise TelegramGatewayPermanentError("Queued vehicle media cannot be read.") from error

    content_type = mimetypes.guess_type(file_field.name)[0] or "application/octet-stream"
    file_name = file_field.name.rsplit("/", 1)[-1]

    if media_object_type == "car_photo" and content_type != "image/jpeg":
        # Telegram's sendPhoto is most reliable with JPEG. Keep the original
        # website asset untouched and convert only the outbound upload bytes.
        try:
            from io import BytesIO
            from PIL import Image

            image = Image.open(BytesIO(file_data)).convert("RGB")
            converted = BytesIO()
            image.save(converted, format="JPEG", quality=92, optimize=True)
            file_data = converted.getvalue()
            file_name = f"{file_name.rsplit('.', 1)[0]}.jpg"
            content_type = "image/jpeg"
        except Exception as error:
            raise TelegramGatewayPermanentError(
                "Queued vehicle image cannot be converted for Telegram."
            ) from error

    return {
        "kind": "photo" if media_object_type == "car_photo" else "video",
        "file_name": file_name,
        "file_data": file_data,
        "content_type": content_type,
    }


def _record_outbox_failure(*, outbox_id, transient, error):
    from .telegram.gateway import TelegramGatewayPermanentError

    with transaction.atomic():
        outbox_message = TelegramOutboxMessage.objects.select_for_update().get(pk=outbox_id)

        if outbox_message.status != TelegramOutboxMessage.Status.SENDING:
            return {"outcome": "superseded"}

        max_attempts = max(int(settings.TELEGRAM_OUTBOX_MAX_ATTEMPTS), 1)
        can_retry = transient and outbox_message.attempt_count < max_attempts

        if can_retry:
            countdown_seconds = _retry_delay_seconds(outbox_message.attempt_count)
            outbox_message.status = TelegramOutboxMessage.Status.RETRY
            outbox_message.next_attempt_at = timezone.now() + timedelta(
                seconds=countdown_seconds
            )
        else:
            countdown_seconds = 0
            outbox_message.status = TelegramOutboxMessage.Status.FAILED
            outbox_message.next_attempt_at = None

        outbox_message.delivery_started_at = None
        outbox_message.last_error_summary = (
            "پیکربندی یا درخواست تلگرام دائماً نامعتبر بود."
            if isinstance(error, TelegramGatewayPermanentError)
            else "ارسال پیام تلگرام با خطای موقت روبه‌رو شد."
        )
        outbox_message.save(
            update_fields=[
                "status",
                "next_attempt_at",
                "delivery_started_at",
                "last_error_summary",
            ]
        )

        return {
            "outcome": "retry" if can_retry else "failed",
            "countdown_seconds": countdown_seconds,
        }


def deliver_telegram_outbox_message(*, outbox_id, gateway=None):
    """Sends one claimed outbox message through an injected or HTTP gateway."""

    outbox_message = _claim_telegram_outbox_message(outbox_id=outbox_id)

    if outbox_message is None:
        return {"outcome": "not_due"}

    from .telegram.gateway import (
        TelegramGatewayPermanentError,
        TelegramGatewayTransientError,
        TelegramHTTPGateway,
    )

    gateway = gateway or TelegramHTTPGateway()

    try:
        if outbox_message.operation == TelegramOutboxMessage.Operation.SEND_MESSAGE:
            telegram_result = gateway.send_message(
                chat_id=outbox_message.chat_id,
                text=outbox_message.body,
                reply_markup=outbox_message.reply_markup,
                reply_to_message_id=outbox_message.reply_to_message_id,
            )
        elif outbox_message.operation == TelegramOutboxMessage.Operation.EDIT_MESSAGE:
            telegram_result = gateway.edit_message_text(
                chat_id=outbox_message.chat_id,
                message_id=outbox_message.target_message_id,
                text=outbox_message.body,
                reply_markup=outbox_message.reply_markup,
            )
        elif outbox_message.operation in {
            TelegramOutboxMessage.Operation.SEND_PHOTO,
            TelegramOutboxMessage.Operation.SEND_VIDEO,
        }:
            media_item = _load_outbox_vehicle_media(
                outbox_message=outbox_message
            )
            if outbox_message.operation == TelegramOutboxMessage.Operation.SEND_PHOTO:
                telegram_result = gateway.send_photo(
                    chat_id=outbox_message.chat_id,
                    file_name=media_item["file_name"],
                    file_data=media_item["file_data"],
                    content_type=media_item["content_type"],
                    caption=outbox_message.body,
                )
            else:
                telegram_result = gateway.send_video(
                    chat_id=outbox_message.chat_id,
                    file_name=media_item["file_name"],
                    file_data=media_item["file_data"],
                    content_type=media_item["content_type"],
                    caption=outbox_message.body,
                )
        elif outbox_message.operation == TelegramOutboxMessage.Operation.SEND_MEDIA_GROUP:
            media_items = [
                _load_vehicle_media_reference(
                    media_object_type=reference["type"],
                    media_object_id=reference["id"],
                )
                for reference in _outbox_media_refs(outbox_message=outbox_message)
            ]
            telegram_result = gateway.send_media_group(
                chat_id=outbox_message.chat_id,
                media_items=media_items,
                caption=outbox_message.body,
            )
        elif outbox_message.operation == TelegramOutboxMessage.Operation.EDIT_MEDIA_CAPTION:
            telegram_result = gateway.edit_message_caption(
                chat_id=outbox_message.chat_id,
                message_id=outbox_message.target_message_id,
                caption=outbox_message.body,
            )
        elif outbox_message.operation == TelegramOutboxMessage.Operation.DELETE_MESSAGE:
            telegram_result = gateway.delete_message(
                chat_id=outbox_message.chat_id,
                message_id=outbox_message.target_message_id,
            )
        elif outbox_message.operation == TelegramOutboxMessage.Operation.ANSWER_CALLBACK:
            telegram_result = gateway.answer_callback_query(
                callback_query_id=outbox_message.callback_query_id,
                text=outbox_message.body,
            )
        else:
            raise TelegramGatewayPermanentError("Unsupported Telegram operation.")
    except TelegramGatewayTransientError as error:
        return _record_outbox_failure(
            outbox_id=outbox_message.pk,
            transient=True,
            error=error,
        )
    except TelegramGatewayPermanentError as error:
        return _record_outbox_failure(
            outbox_id=outbox_message.pk,
            transient=False,
            error=error,
        )
    except Exception as error:
        # Unknown transport failures are retryable, but their raw detail is not persisted.
        return _record_outbox_failure(
            outbox_id=outbox_message.pk,
            transient=True,
            error=error,
        )

    return _record_outbox_success(
        outbox_id=outbox_message.pk,
        telegram_result=telegram_result,
    )


def get_due_telegram_outbox_message_ids(*, limit=100):
    """Returns due work for the periodic recovery task without claiming it."""

    now = timezone.now()
    stale_before = now - timedelta(
        seconds=getattr(settings, "TELEGRAM_OUTBOX_SENDING_TIMEOUT_SECONDS", 300)
    )

    return list(
        TelegramOutboxMessage.objects.filter(
            Q(status=TelegramOutboxMessage.Status.PENDING)
            | Q(
                status=TelegramOutboxMessage.Status.RETRY,
                next_attempt_at__lte=now,
            )
            | Q(
                status=TelegramOutboxMessage.Status.SENDING,
                delivery_started_at__lte=stale_before,
            )
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )


@transaction.atomic
def retry_failed_telegram_outbox_message(*, outbox_id, actor):
    """Safely re-queue one failed outbound message after administrator review."""

    _require_system_administrator(actor=actor)
    outbox_message = TelegramOutboxMessage.objects.select_for_update().get(pk=outbox_id)

    if outbox_message.status != TelegramOutboxMessage.Status.FAILED:
        raise ValidationError("فقط پیام‌های ناموفق Telegram قابل ارسال مجدد هستند.")

    outbox_message.status = TelegramOutboxMessage.Status.PENDING
    outbox_message.next_attempt_at = None
    outbox_message.delivery_started_at = None
    outbox_message.last_error_summary = ""
    outbox_message.save(
        update_fields=[
            "status",
            "next_attempt_at",
            "delivery_started_at",
            "last_error_summary",
        ]
    )
    transaction.on_commit(
        lambda outbox_pk=outbox_message.pk: _schedule_outbox_delivery(outbox_pk)
    )
    return outbox_message
