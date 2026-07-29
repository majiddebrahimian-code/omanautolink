from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Stage(models.Model):
    name = models.CharField(max_length=120)
    order = models.PositiveIntegerField(default=0)
    default_duration_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.name


class StageTransition(models.Model):
    from_stage = models.ForeignKey(
        Stage,
        on_delete=models.PROTECT,
        related_name="outgoing_transitions",
    )
    to_stage = models.ForeignKey(
        Stage,
        on_delete=models.PROTECT,
        related_name="incoming_transitions",
    )

    estimated_duration_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["from_stage__order", "to_stage__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_stage", "to_stage"],
                name="unique_stage_transition",
            ),
            models.CheckConstraint(
                check=~models.Q(from_stage=models.F("to_stage")),
                name="stage_transition_cannot_point_to_itself",
            ),
        ]

    def clean(self):
        if (
            self.from_stage_id
            and self.to_stage_id
            and self.from_stage.order >= self.to_stage.order
        ):
            raise ValidationError(
                "A stage transition must move forward in the stage order."
            )

    def __str__(self):
        return (
            f"{self.from_stage.name} → {self.to_stage.name} "
            f"({self.estimated_duration_days} days)"
        )


class TrackingEvent(models.Model):
    class EventType(models.TextChoices):
        TRACKING_STARTED = "tracking_started", "Tracking started"
        STAGE_CONFIRMED = "stage_confirmed", "Stage entered"
        STAGE_COMPLETED = "stage_completed", "Stage completed"
        STAGE_CORRECTED = "stage_corrected", "Stage corrected"
        STAGE_SKIPPED = "stage_skipped", "Stage skipped"
        STAGE_ARCHIVED = "stage_archived", "Stage archived"

    class Source(models.TextChoices):
        SYSTEM = "system", "System"
        ADMIN_DASHBOARD = "admin_dashboard", "Admin dashboard"
        TELEGRAM_BOT = "telegram_bot", "Telegram bot"
        EXCEL_IMPORT = "excel_import", "Excel import"

    car = models.ForeignKey(
        "cars.Car",
        on_delete=models.PROTECT,
        related_name="tracking_events",
    )

    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
    )

    previous_stage = models.ForeignKey(
        Stage,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="tracking_events_from",
    )
    new_stage = models.ForeignKey(
        Stage,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="tracking_events_to",
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="tracking_events",
    )

    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.SYSTEM,
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["car", "created_at"],
                name="tracking_event_car_time_idx",
            )
        ]
        permissions = [
            (
                "confirm_tracking_stage",
                "Can confirm an assigned tracking stage",
            ),
            (
                "import_tracking_stage_updates",
                "Can import tracking stage updates",
            ),
            (
                "skip_tracking_stage",
                "Can skip a tracking stage",
            ),
            (
                "correct_tracking_stage",
                "Can correct tracking stages",
            ),
            (
                "archive_tracking_stage",
                "Can archive a tracking stage",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Tracking events are immutable and cannot be changed."
            )

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Tracking events are immutable and cannot be deleted.")

    def __str__(self):
        return f"{self.car} - {self.event_type} - " f"{self.created_at:%Y-%m-%d %H:%M}"


class CarStageProgress(models.Model):
    car = models.ForeignKey(
        "cars.Car",
        on_delete=models.CASCADE,
        related_name="stage_progress",
    )
    stage = models.ForeignKey(
        Stage,
        on_delete=models.CASCADE,
        related_name="progress_records",
    )

    planned_date = models.DateField(
        blank=True,
        null=True,
    )

    actual_arrival = models.DateTimeField(
        blank=True,
        null=True,
    )
    confirmed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="confirmed_stages",
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True,
    )
    completed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="completed_stages",
    )

    skipped_at = models.DateTimeField(
        blank=True,
        null=True,
    )
    skipped_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="skipped_stages",
    )

    class Meta:
        unique_together = ["car", "stage"]
        ordering = ["stage__order"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(actual_arrival__isnull=True)
                    | models.Q(skipped_at__isnull=True)
                ),
                name="progress_cannot_be_confirmed_and_skipped",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(completed_at__isnull=True)
                    | models.Q(actual_arrival__isnull=False)
                ),
                name="progress_cannot_complete_before_entry",
            ),
        ]

    @property
    def state(self):
        if self.skipped_at is not None:
            return "skipped"

        if self.completed_at is not None:
            return "completed"

        if self.actual_arrival is not None:
            return "entered"

        return "pending"

    def __str__(self):
        return f"{self.car.tracking_code} @ {self.stage.name}"
