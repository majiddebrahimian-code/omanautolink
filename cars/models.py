from django.db import models
from django.conf import settings

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.urls import reverse
from django.utils.text import slugify

from tracking.models import Stage
from customers.models import Customer


def car_spin_frame_upload_to(instance, filename):
    """Keep rotation-only media separate from the regular vehicle gallery."""

    car_identifier = instance.car_id or "unassigned"
    return f"cars/spins/{car_identifier}/{filename}"


class Car(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        FOR_SALE = "for_sale", "For sale"
        ON_HOLD = "on_hold", "On hold"
        SOLD = "sold", "Sold"
        IN_TRANSIT = "in_transit", "In transit"
        DELIVERED = "delivered", "Delivered"

    tracking_code = models.CharField(max_length=40, unique=True, blank=True, null=True)
    title = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=240,
        unique=True,
        blank=True,
        null=True,
        allow_unicode=True,
    )
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.PositiveIntegerField(blank=True, null=True)
    color = models.CharField(max_length=50, blank=True)
    mileage = models.PositiveIntegerField(blank=True, null=True)
    price_amount = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=120, blank=True)
    seo_title = models.CharField(max_length=160, blank=True)
    seo_description = models.CharField(max_length=320, blank=True)
    seo_keywords = models.CharField(max_length=500, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    is_featured = models.BooleanField(default=False)
    spin_360_enabled = models.BooleanField(default=False)

    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="cars",
    )
    current_stage = models.ForeignKey(
        Stage,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="cars_at_stage",
    )
    target_delivery = models.DateField(blank=True, null=True)

    channel_message_ids = models.JSONField(blank=True, null=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "is_deleted", "is_featured"],
                name="public_car_visibility_idx",
            )
        ]
        permissions = [
            (
                "publish_vehicle",
                "Can publish a vehicle for sale",
            ),
            (
                "hold_vehicle",
                "Can place a vehicle on hold",
            ),
            (
                "release_vehicle_hold",
                "Can release a vehicle hold",
            ),
            (
                "sell_vehicle",
                "Can mark a vehicle as sold",
            ),
            (
                "archive_vehicle",
                "Can archive a vehicle",
            ),
        ]

    def __str__(self):
        identifier = self.tracking_code or f"Car #{self.pk}"
        return f"{identifier} — {self.title}"

    def _generate_unique_slug(self):
        base_slug = slugify(self.title, allow_unicode=True).strip("-") or "vehicle"
        base_slug = base_slug[:220]
        candidate = base_slug
        suffix_number = 2
        existing_cars = type(self).objects.exclude(pk=self.pk)

        while existing_cars.filter(slug=candidate).exists():
            suffix = f"-{suffix_number}"
            candidate = f"{base_slug[: 240 - len(suffix)]}{suffix}"
            suffix_number += 1

        return candidate

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse(
            "cars:vehicle_detail",
            kwargs={
                "slug": self.slug or "vehicle",
                "pk": self.pk,
            },
        )

    @property
    def price_display(self):
        if self.price_amount <= 0:
            return "ارزنده"
        return f"{self.price_amount:,.0f} تومان"


class CarPhoto(models.Model):
    car = models.ForeignKey(
        Car,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField(upload_to="cars/", blank=True, null=True)
    telegram_file_id = models.CharField(max_length=200, blank=True, null=True)
    is_cover = models.BooleanField(default=False)
    alt_text = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-is_cover", "sort_order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["car"],
                condition=models.Q(is_cover=True),
                name="one_cover_photo_per_car",
            )
        ]

    def __str__(self):
        return f"Photo for {self.car.tracking_code}"


class CarSpinFrame(models.Model):
    """One ordered visual frame for a car's optional 360-degree viewer.

    These frames intentionally do not share the ``CarPhoto`` gallery.  A
    rotation sequence can contain 12–36 files and must never alter a vehicle's
    normal cover image, public gallery, or structured-data image list.
    """

    car = models.ForeignKey(
        Car,
        on_delete=models.CASCADE,
        related_name="spin_frames",
    )
    image = models.ImageField(
        upload_to=car_spin_frame_upload_to,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])],
        width_field="image_width",
        height_field="image_height",
    )
    sequence = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    image_width = models.PositiveIntegerField(blank=True, null=True, editable=False)
    image_height = models.PositiveIntegerField(blank=True, null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["car", "sequence"],
                name="car_spin_frame_unique_sequence",
            ),
            models.CheckConstraint(
                check=models.Q(sequence__gte=1),
                name="car_spin_frame_sequence_gte_1",
            ),
        ]
        verbose_name = "فریم نمای ۳۶۰ خودرو"
        verbose_name_plural = "فریم‌های نمای ۳۶۰ خودرو"

    def __str__(self):
        return f"{self.car} — frame {self.sequence}"


class VehicleHold(models.Model):
    car = models.ForeignKey(
        Car,
        on_delete=models.CASCADE,
        related_name="holds",
    )

    customer_name = models.CharField(max_length=200, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_vehicle_holds",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    expires_at = models.DateTimeField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    released_at = models.DateTimeField(blank=True, null=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="released_vehicle_holds",
    )
    release_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["car"],
                condition=models.Q(is_active=True),
                name="one_active_hold_per_car",
            )
        ]

    def __str__(self):
        status = "Active" if self.is_active else "Released"
        identifier = self.car.tracking_code or self.car.title
        return f"{identifier} - {status}"


class VehicleArchiveEvent(models.Model):
    class Action(models.TextChoices):
        ARCHIVED = "archived", "Archived"
        RESTORED = "restored", "Restored"

    class Source(models.TextChoices):
        SYSTEM = "system", "System"
        ADMIN_DASHBOARD = "admin_dashboard", "Admin dashboard"
        WEBSITE = "website", "Website"
        TELEGRAM_BOT = "telegram_bot", "Telegram bot"

    car = models.ForeignKey(
        Car,
        on_delete=models.PROTECT,
        related_name="archive_events",
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
    )

    previous_status = models.CharField(
        max_length=20,
        choices=Car.Status.choices,
    )
    new_status = models.CharField(
        max_length=20,
        choices=Car.Status.choices,
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vehicle_archive_events",
    )

    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.SYSTEM,
    )

    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["car", "created_at"],
                name="vehicle_archive_car_time_idx",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویدادهای بایگانی خودرو غیرقابل ویرایش هستند.")

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("رویدادهای بایگانی خودرو غیرقابل حذف هستند.")

    def __str__(self):
        return f"{self.car} - {self.action} - " f"{self.created_at:%Y-%m-%d %H:%M}"


class VehicleInventoryEvent(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"

    class Source(models.TextChoices):
        BACKOFFICE = "backoffice", "Backoffice"
        TELEGRAM_BOT = "telegram_bot", "Telegram bot"
        DJANGO_ADMIN = "django_admin", "Django admin"

    car = models.ForeignKey(
        Car,
        on_delete=models.PROTECT,
        related_name="inventory_events",
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vehicle_inventory_events",
    )

    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.BACKOFFICE,
    )

    changes = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["car", "created_at"],
                name="vehicle_inv_event_time_idx",
            )
        ]
        verbose_name = "رویداد موجودی ماشین"
        verbose_name_plural = "رویدادهای موجودی ماشین"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویدادهای موجودی ماشین غیرقابل‌ویرایش هستند.")

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("رویدادهای موجودی ماشین غیرقابل‌حذف هستند.")

    def __str__(self):
        return f"{self.car} - {self.action} - {self.created_at:%Y-%m-%d %H:%M}"
