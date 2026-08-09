from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class TelegramChannel(models.Model):
    """One administrator-managed Telegram channel available for publications."""

    name = models.CharField(max_length=120, unique=True)
    chat_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    publish_available_vehicles = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        verbose_name = "کانال Telegram"
        verbose_name_plural = "کانال‌های Telegram"

    def clean(self):
        if self.chat_id == 0:
            raise ValidationError("شناسهٔ کانال Telegram نمی‌تواند صفر باشد.")

    def __str__(self):
        return self.name


class TelegramIntegrationSettings(models.Model):
    """Singleton, non-secret operational settings for the Telegram integration."""

    class InboundMode(models.TextChoices):
        WEBHOOK = "webhook", "Webhook"
        POLLING = "polling", "Long polling"

    class SoldPublicationAction(models.TextChoices):
        MARK_SOLD = "mark_sold", "Mark as sold"
        DELETE = "delete", "Delete post"

    inbound_mode = models.CharField(
        max_length=20,
        choices=InboundMode.choices,
        default=InboundMode.WEBHOOK,
    )
    customer_notifications_enabled = models.BooleanField(default=True)
    staff_bot_enabled = models.BooleanField(default=True)
    vehicle_channel_sync_enabled = models.BooleanField(default=False)
    default_vehicle_channel = models.ForeignKey(
        TelegramChannel,
        on_delete=models.SET_NULL,
        related_name="default_for_settings",
        blank=True,
        null=True,
    )
    sold_vehicle_publication_action = models.CharField(
        max_length=20,
        choices=SoldPublicationAction.choices,
        default=SoldPublicationAction.MARK_SOLD,
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_telegram_integration_settings",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "تنظیمات Telegram"
        verbose_name_plural = "تنظیمات Telegram"

    def clean(self):
        if self.pk not in {None, 1}:
            raise ValidationError("فقط یک رکورد تنظیمات Telegram مجاز است.")
        if (
            self.vehicle_channel_sync_enabled
            and self.default_vehicle_channel_id is None
        ):
            raise ValidationError(
                "برای فعال‌سازی همگام‌سازی کانال، کانال پیش‌فرض را انتخاب کنید."
            )

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)


class TelegramStaffLink(models.Model):
    """
    Historical link between one internal Django user and one Telegram account.

    Telegram usernames are display data only. Authorization always uses the
    stable numeric Telegram user ID and the linked Django user.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="telegram_staff_links",
    )
    telegram_user_id = models.BigIntegerField()
    telegram_chat_id = models.BigIntegerField()
    telegram_username = models.CharField(max_length=255, blank=True)
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)

    is_active = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    unlinked_at = models.DateTimeField(blank=True, null=True)
    unlinked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="revoked_telegram_staff_links",
        blank=True,
        null=True,
    )
    unlink_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-linked_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(is_active=True),
                name="one_active_telegram_link_per_staff_user",
            ),
            models.UniqueConstraint(
                fields=["telegram_user_id"],
                condition=Q(is_active=True),
                name="one_active_staff_link_per_telegram_user",
            ),
            models.UniqueConstraint(
                fields=["telegram_chat_id"],
                condition=Q(is_active=True),
                name="one_active_staff_link_per_telegram_chat",
            ),
        ]
        indexes = [
            models.Index(
                fields=["telegram_user_id", "is_active"],
                name="telegram_staff_user_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} ↔ Telegram {self.telegram_user_id}"


class TelegramStaffLinkToken(models.Model):
    """A short-lived, one-time code used to link an internal staff account."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="telegram_link_tokens",
    )
    code_hash = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_telegram_link_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    used_telegram_user_id = models.BigIntegerField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="revoked_telegram_link_tokens",
        blank=True,
        null=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "expires_at"],
                name="telegram_token_user_expiry_idx",
            ),
        ]

    def __str__(self):
        return f"Telegram link token for {self.user}"


class TelegramCustomerActivationToken(models.Model):
    """
    A one-time, short-lived customer code for activating Telegram tracking.

    The raw code is intentionally never persisted.  It is shown once to the
    authorized salesperson, who can share it with the customer after sale.
    """

    car = models.ForeignKey(
        "cars.Car",
        on_delete=models.PROTECT,
        related_name="telegram_customer_activation_tokens",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="telegram_activation_tokens",
    )
    code_hash = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_customer_telegram_activation_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    used_telegram_user_id = models.BigIntegerField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="revoked_customer_telegram_activation_tokens",
        blank=True,
        null=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            (
                "issue_customer_telegram_activation",
                "Can issue a customer Telegram activation code",
            ),
        ]
        indexes = [
            models.Index(
                fields=["car", "expires_at"],
                name="tg_cust_token_car_exp_idx",
            ),
            models.Index(
                fields=["customer", "expires_at"],
                name="tg_cust_token_user_exp_idx",
            ),
        ]

    def __str__(self):
        return f"Customer Telegram activation token for {self.car}"


class CustomerTelegramSubscription(models.Model):
    """A verified Telegram identity subscribed to one sold vehicle's updates."""

    car = models.ForeignKey(
        "cars.Car",
        on_delete=models.PROTECT,
        related_name="telegram_customer_subscriptions",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="telegram_tracking_subscriptions",
    )
    telegram_user_id = models.BigIntegerField()
    telegram_chat_id = models.BigIntegerField()
    telegram_username = models.CharField(max_length=255, blank=True)
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    unsubscribed_at = models.DateTimeField(blank=True, null=True)
    unsubscribe_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-subscribed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["car"],
                condition=Q(is_active=True),
                name="one_active_customer_subscription_per_car",
            ),
        ]
        indexes = [
            models.Index(
                fields=["telegram_user_id", "is_active"],
                name="tg_customer_user_active_idx",
            ),
            models.Index(
                fields=["telegram_chat_id", "is_active"],
                name="tg_customer_chat_active_idx",
            ),
        ]

    def __str__(self):
        return f"Customer Telegram subscription for {self.car}"


class TelegramInboundUpdate(models.Model):
    """
    Sanitized receipt for one Telegram update.

    Raw updates are deliberately not stored because commands can contain a
    one-time link code or a tracking code. The unique update ID provides
    idempotency without retaining sensitive command arguments.
    """

    class UpdateType(models.TextChoices):
        MESSAGE = "message", "Message"
        CALLBACK_QUERY = "callback_query", "Callback query"
        UNSUPPORTED = "unsupported", "Unsupported"

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    telegram_update_id = models.BigIntegerField(unique=True)
    telegram_user_id = models.BigIntegerField(blank=True, null=True)
    telegram_chat_id = models.BigIntegerField(blank=True, null=True)
    telegram_message_id = models.BigIntegerField(blank=True, null=True)
    update_type = models.CharField(
        max_length=30,
        choices=UpdateType.choices,
    )
    command_name = models.CharField(max_length=60, blank=True)
    staff_link = models.ForeignKey(
        TelegramStaffLink,
        on_delete=models.PROTECT,
        related_name="inbound_updates",
        blank=True,
        null=True,
    )
    customer_subscription = models.ForeignKey(
        CustomerTelegramSubscription,
        on_delete=models.PROTECT,
        related_name="inbound_updates",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RECEIVED,
    )
    error_summary = models.CharField(max_length=500, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(
                fields=["telegram_user_id", "received_at"],
                name="telegram_update_user_time_idx",
            ),
            models.Index(
                fields=["status", "received_at"],
                name="tg_update_status_time_idx",
            ),
        ]

    def __str__(self):
        return f"Telegram update {self.telegram_update_id}"


class TelegramStageConfirmationSession(models.Model):
    """Short-lived, staff-bound preview before the final stage confirmation."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "Failed"

    public_token = models.CharField(max_length=64, unique=True)
    staff_link = models.ForeignKey(
        TelegramStaffLink,
        on_delete=models.PROTECT,
        related_name="confirmation_sessions",
    )
    car = models.ForeignKey(
        "cars.Car",
        on_delete=models.PROTECT,
        related_name="telegram_confirmation_sessions",
    )
    stage = models.ForeignKey(
        "tracking.Stage",
        on_delete=models.PROTECT,
        related_name="telegram_confirmation_sessions",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    failure_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["staff_link", "status", "expires_at"],
                name="tg_session_staff_state_idx",
            ),
        ]

    def __str__(self):
        return f"Telegram confirmation {self.public_token}"


class TelegramOutboxMessage(models.Model):
    """Durable outbound Telegram work item with application-level idempotency."""

    class Operation(models.TextChoices):
        SEND_MESSAGE = "send_message", "Send message"
        ANSWER_CALLBACK = "answer_callback", "Answer callback"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        RETRY = "retry", "Retry"
        FAILED = "failed", "Failed"

    operation = models.CharField(
        max_length=30,
        choices=Operation.choices,
        default=Operation.SEND_MESSAGE,
    )
    chat_id = models.BigIntegerField(blank=True, null=True)
    callback_query_id = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    reply_markup = models.JSONField(blank=True, null=True)
    reply_to_message_id = models.BigIntegerField(blank=True, null=True)
    message_type = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=200, unique=True)
    inbound_update = models.ForeignKey(
        TelegramInboundUpdate,
        on_delete=models.PROTECT,
        related_name="outbox_messages",
        blank=True,
        null=True,
    )
    staff_link = models.ForeignKey(
        TelegramStaffLink,
        on_delete=models.PROTECT,
        related_name="outbox_messages",
        blank=True,
        null=True,
    )
    customer_subscription = models.ForeignKey(
        CustomerTelegramSubscription,
        on_delete=models.PROTECT,
        related_name="outbox_messages",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(blank=True, null=True)
    delivery_started_at = models.DateTimeField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    telegram_message_id = models.BigIntegerField(blank=True, null=True)
    last_error_summary = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at"],
                name="telegram_outbox_state_next_idx",
            ),
            models.Index(
                fields=["chat_id", "created_at"],
                name="telegram_outbox_chat_time_idx",
            ),
        ]

    def clean(self):
        if self.operation == self.Operation.SEND_MESSAGE and self.chat_id is None:
            raise ValidationError("پیام ارسالی تلگرام باید شناسهٔ چت داشته باشد.")

        if (
            self.operation == self.Operation.ANSWER_CALLBACK
            and not self.callback_query_id.strip()
        ):
            raise ValidationError("پاسخ Callback تلگرام باید شناسهٔ Callback داشته باشد.")

    def __str__(self):
        return f"Telegram {self.operation} ({self.status}) #{self.pk}"


class CustomerTrackingNotification(models.Model):
    """Durable, idempotent notification intent for one tracking event."""

    tracking_event = models.ForeignKey(
        "tracking.TrackingEvent",
        on_delete=models.PROTECT,
        related_name="customer_notifications",
    )
    subscription = models.ForeignKey(
        CustomerTelegramSubscription,
        on_delete=models.PROTECT,
        related_name="tracking_notifications",
    )
    outbox_message = models.OneToOneField(
        TelegramOutboxMessage,
        on_delete=models.PROTECT,
        related_name="customer_tracking_notification",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tracking_event", "subscription"],
                name="one_customer_notification_per_tracking_event",
            ),
        ]
        indexes = [
            models.Index(
                fields=["subscription", "created_at"],
                name="tg_cust_notice_sub_idx",
            ),
        ]

    def __str__(self):
        return (
            f"Customer notification for tracking event "
            f"#{self.tracking_event_id}"
        )
