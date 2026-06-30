from django.contrib import admin
from .models import StaffProfile


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "phone"]
    filter_horizontal = ["assigned_stages"]
