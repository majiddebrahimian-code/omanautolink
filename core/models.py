from django.db import models


class SiteSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)

    def __str__(self):
        return self.key


class OrderRequest(models.Model):
    class Type(models.TextChoices):
        ORDER = "order", "Car order"
        CONSULT = "consult", "Consultation"

    customer_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    type = models.CharField(max_length=10, choices=Type.choices, default=Type.ORDER)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="new")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.type} from {self.customer_name}"


class FaqCategory(models.Model):
    name = models.CharField(max_length=120)
    emoji = models.CharField(max_length=10, blank=True, default="❓")

    class Meta:
        verbose_name_plural = "FAQ categories"

    def __str__(self):
        return self.name


class FaqItem(models.Model):
    category = models.ForeignKey(
        FaqCategory,
        on_delete=models.CASCADE,
        related_name="items",
    )
    question = models.TextField()
    answer = models.TextField()

    def __str__(self):
        return self.question[:60]
