"""Shared application services for Telegram integration workflows.

The Telegram adapter is intentionally thin.  It obtains a verified staff
identity here, creates a short-lived confirmation session here, and delegates
the final tracking change to ``tracking.services.confirm_stage``.
"""

import logging
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
    inbound_update=None,
    staff_link=None,
    customer_subscription=None,
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
