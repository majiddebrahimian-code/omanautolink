from django.db import models


class SiteSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)

    def __str__(self):
        return self.key


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
