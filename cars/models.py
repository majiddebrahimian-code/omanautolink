from django.db import models
from django.conf import settings

from tracking.models import Stage
from customers.models import Customer


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
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.PositiveIntegerField(blank=True, null=True)
    color = models.CharField(max_length=50, blank=True)
    mileage = models.PositiveIntegerField(blank=True, null=True)
    price_amount = models.DecimalField(max_digits=15, decimal_places=0, default=0)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=120, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    is_featured = models.BooleanField(default=False)

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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        identifier = self.tracking_code or f"Car #{self.pk}"
        return f"{identifier} — {self.title}"

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

    def __str__(self):
        return f"Photo for {self.car.tracking_code}"


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
