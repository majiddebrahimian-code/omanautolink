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
