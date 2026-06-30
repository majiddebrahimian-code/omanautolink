from django.contrib import admin
from .models import Car, CarPhoto


class CarPhotoInline(admin.TabularInline):
    model = CarPhoto
    extra = 1


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = [
        "tracking_code",
        "title",
        "brand",
        "status",
        "customer",
        "current_stage",
    ]
    list_filter = ["status", "brand", "is_featured"]
    search_fields = ["tracking_code", "title", "brand", "model"]
    inlines = [CarPhotoInline]
