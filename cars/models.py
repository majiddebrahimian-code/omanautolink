from django.db import models

from tracking.models import Stage
from customers.models import Customer


class Car(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        FOR_SALE = "for_sale", "For sale"
        SOLD = "sold", "Sold"
        IN_TRANSIT = "in_transit", "In transit"
        DELIVERED = "delivered", "Delivered"

    tracking_code = models.CharField(max_length=40, unique=True)
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
        return f"{self.tracking_code} — {self.title}"

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
