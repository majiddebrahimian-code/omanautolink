from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User

from tracking.models import Stage


class StaffProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )
    phone = models.CharField(max_length=20, blank=True)
    assigned_stages = models.ManyToManyField(
        Stage,
        blank=True,
        related_name="staff_members",
    )

    def __str__(self):
        return f"Profile of {self.user.username}"


class StaffManagementEvent(models.Model):
    """Immutable administrative history for employee-account changes.

    The project already preserves vehicle and tracking history.  Employee
    administration is equally sensitive: a future investigation must be able
    to answer who changed a role, permission, stage assignment, or account
    state, without retaining secrets such as passwords or Telegram link codes.
    """

    class Action(models.TextChoices):
        CREATED = "created", "Employee created"
        UPDATED = "updated", "Employee updated"
        PASSWORD_RESET = "password_reset", "Password reset"
        DEACTIVATED = "deactivated", "Employee deactivated"
        REACTIVATED = "reactivated", "Employee reactivated"
        TELEGRAM_LINK_ISSUED = "telegram_link_issued", "Telegram link issued"
        TELEGRAM_LINK_REVOKED = "telegram_link_revoked", "Telegram link revoked"

    class Source(models.TextChoices):
        BACKOFFICE = "backoffice", "Backoffice"
        SYSTEM = "system", "System"

    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="staff_management_events",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="performed_staff_management_events",
    )
    action = models.CharField(max_length=40, choices=Action.choices)
    changes = models.JSONField(default=dict, blank=True)
    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.BACKOFFICE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["staff_user", "created_at"],
                name="staff_mgmt_evt_user_ts_idx",
            )
        ]
        verbose_name = "رویداد مدیریت کارمند"
        verbose_name_plural = "رویدادهای مدیریت کارکنان"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویدادهای مدیریت کارکنان غیرقابل‌ویرایش هستند.")

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("رویدادهای مدیریت کارکنان غیرقابل‌حذف هستند.")

    def __str__(self):
        return (
            f"{self.staff_user} - {self.action} - "
            f"{self.created_at:%Y-%m-%d %H:%M}"
        )
