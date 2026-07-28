from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Customer(models.Model):
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    telegram_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
    )

    def __str__(self):
        return self.full_name


class CustomVehicleRequest(models.Model):
    class Source(models.TextChoices):
        WEBSITE = "website", "وب‌سایت"
        TELEGRAM_BOT = "telegram_bot", "ربات تلگرام"

    class Status(models.TextChoices):
        NEW = "new", "جدید"
        SOLD = "sold", "فروخته‌شده"

    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    telegram_id = models.CharField(max_length=50, blank=True)

    desired_vehicle_description = models.TextField(
        help_text="توضیح آزاد مشتری دربارهٔ خودروی موردنظر",
    )

    preferred_brand = models.CharField(max_length=100, blank=True)
    preferred_model = models.CharField(max_length=100, blank=True)

    preferred_year_from = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
    )
    preferred_year_to = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
    )

    budget_amount = models.DecimalField(
        max_digits=15,
        decimal_places=0,
    )

    preferred_color = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)

    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.WEBSITE,
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.NEW,
    )

    sold_car = models.OneToOneField(
        "cars.Car",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="custom_vehicle_request",
    )
    sold_at = models.DateTimeField(blank=True, null=True)
    sold_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="sold_custom_vehicle_requests",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(preferred_year_from__isnull=True)
                    | models.Q(preferred_year_to__isnull=True)
                    | models.Q(preferred_year_from__lte=models.F("preferred_year_to"))
                ),
                name="custom_vehicle_request_valid_year_range",
            ),
            models.CheckConstraint(
                check=models.Q(budget_amount__gt=0),
                name="custom_vehicle_request_positive_budget",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(
                        status="new",
                        sold_car__isnull=True,
                        sold_at__isnull=True,
                        sold_by__isnull=True,
                    )
                    | models.Q(
                        status="sold",
                        sold_car__isnull=False,
                        sold_at__isnull=False,
                        sold_by__isnull=False,
                    )
                ),
                name="custom_vehicle_request_consistent_sale_state",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.preferred_year_from is not None
            and self.preferred_year_to is not None
            and self.preferred_year_from > self.preferred_year_to
        ):
            raise ValidationError(
                {"preferred_year_to": ("سال پایان نمی‌تواند از سال شروع کمتر باشد.")}
            )

        if self.budget_amount is not None and self.budget_amount <= 0:
            raise ValidationError({"budget_amount": "بودجه باید بزرگ‌تر از صفر باشد."})

    def __str__(self):
        return f"Custom request #{self.pk} from {self.full_name}"


class CustomVehicleRequestReadReceipt(models.Model):
    """
    Records which internal employee has opened a customer request.
    """

    vehicle_request = models.ForeignKey(
        CustomVehicleRequest,
        on_delete=models.CASCADE,
        related_name="read_receipts",
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="custom_vehicle_request_read_receipts",
    )

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle_request", "employee"],
                name="one_read_receipt_per_employee_and_request",
            )
        ]

    def __str__(self):
        return f"{self.employee.username} viewed " f"request #{self.vehicle_request_id}"


class SearchLog(models.Model):
    class Source(models.TextChoices):
        WEB = "web", "Website"
        BOT = "bot", "Telegram bot"

    car = models.ForeignKey(
        "cars.Car",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="search_logs",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="search_logs",
    )
    source = models.CharField(max_length=10, choices=Source.choices)
    user_agent = models.CharField(max_length=300, blank=True)
    searched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-searched_at"]

    def __str__(self):
        return f"{self.source} search at {self.searched_at:%Y-%m-%d %H:%M}"
