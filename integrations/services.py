"""Shared application services for Telegram integration workflows.

The Telegram adapter is intentionally thin.  It obtains a verified staff
identity here, creates a short-lived confirmation session here, and delegates
the final tracking change to ``tracking.services.confirm_stage``.
"""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.signing import salted_hmac
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.authorization import require_active_internal_staff

from .models import (
    TelegramInboundUpdate,
    TelegramOutboxMessage,
    TelegramStageConfirmationSession,
    TelegramStaffLink,
    TelegramStaffLinkToken,
)


logger = logging.getLogger(__name__)


def _clean_telegram_identifier(value, field_name):
    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field_name} تلگرام معتبر نیست.")

    if normalized_value <= 0:
        raise ValidationError(f"{field_name} تلگرام معتبر نیست.")

    return normalized_value


def _hash_staff_link_code(code):
    return salted_hmac(
        "integrations.telegram.staff-link-code",
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
    inbound_update=None,
    staff_link=None,
):
    """Creates one durable outbound message and schedules its delivery after commit."""

    outbox_message, created = TelegramOutboxMessage.objects.get_or_create(
        idempotency_key=str(idempotency_key),
        defaults={
            "operation": TelegramOutboxMessage.Operation.SEND_MESSAGE,
            "chat_id": _clean_telegram_identifier(chat_id, "شناسهٔ چت"),
            "body": str(body or ""),
            "reply_markup": reply_markup,
            "reply_to_message_id": reply_to_message_id,
            "message_type": str(message_type),
            "inbound_update": inbound_update,
            "staff_link": staff_link,
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

            if staff_link is not None:
                inbound_update.staff_link = staff_link
                inbound_update.save(update_fields=["staff_link"])

            # The adapter handles messages, while every domain write remains in a service.
            from .telegram.handlers import handle_telegram_inbound_update

            handle_telegram_inbound_update(
                inbound_update=inbound_update,
                parsed=parsed,
                staff_link=staff_link,
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

        return {"outcome": "sent"}


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
