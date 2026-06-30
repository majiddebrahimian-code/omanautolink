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
    planned_date = models.DateField(blank=True, null=True)
    actual_arrival = models.DateTimeField(blank=True, null=True)
    confirmed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="confirmed_stages",
    )

    class Meta:
        unique_together = ["car", "stage"]
        ordering = ["stage__order"]

    def __str__(self):
        return f"{self.car.tracking_code} @ {self.stage.name}"
