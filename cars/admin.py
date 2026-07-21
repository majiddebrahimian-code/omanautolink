from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Car, CarPhoto, VehicleHold
from .services import (
    place_vehicle_on_hold,
    publish_vehicle_for_sale,
    release_vehicle_hold,
)


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

    # Status must be changed through Admin Actions and services.
    readonly_fields = ["status", "tracking_code"]

    actions = [
        "publish_selected_cars",
        "place_selected_vehicle_on_hold",
    ]

    @admin.action(description="Publish selected vehicles for sale")
    def publish_selected_cars(self, request, queryset):
        success_count = 0

        for car in queryset:
            try:
                publish_vehicle_for_sale(car_id=car.id)
            except ValidationError as error:
                self.message_user(
                    request,
                    f"{car}: {' '.join(error.messages)}",
                    level=messages.ERROR,
                )
            else:
                success_count += 1

        if success_count:
            self.message_user(
                request,
                f"{success_count} vehicle(s) published for sale.",
                level=messages.SUCCESS,
            )

    @admin.action(description="Place selected vehicle on hold")
    def place_selected_vehicle_on_hold(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Select exactly one vehicle to place on hold.",
                level=messages.ERROR,
            )
            return

        car = queryset.first()

        try:
            place_vehicle_on_hold(
                car_id=car.id,
                actor=request.user,
            )
        except ValidationError as error:
            self.message_user(
                request,
                " ".join(error.messages),
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                f"{car} was placed on hold.",
                level=messages.SUCCESS,
            )


@admin.register(VehicleHold)
class VehicleHoldAdmin(admin.ModelAdmin):
    list_display = [
        "car",
        "customer_name",
        "customer_phone",
        "created_by",
        "created_at",
        "expires_at",
        "is_active",
        "released_by",
        "released_at",
    ]
    list_filter = ["is_active", "created_at"]
    search_fields = [
        "car__title",
        "car__tracking_code",
        "customer_name",
        "customer_phone",
    ]
    list_select_related = ["car", "created_by", "released_by"]

    readonly_fields = [
        "car",
        "customer_name",
        "customer_phone",
        "created_by",
        "created_at",
        "expires_at",
        "is_active",
        "released_at",
        "released_by",
        "release_note",
    ]

    actions = ["release_selected_holds"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Release selected active holds")
    def release_selected_holds(self, request, queryset):
        success_count = 0

        for hold in queryset:
            try:
                release_vehicle_hold(
                    hold_id=hold.id,
                    actor=request.user,
                    release_note="Released from Django Admin.",
                )
            except ValidationError as error:
                self.message_user(
                    request,
                    f"{hold}: {' '.join(error.messages)}",
                    level=messages.ERROR,
                )
            else:
                success_count += 1

        if success_count:
            self.message_user(
                request,
                f"{success_count} hold(s) released.",
                level=messages.SUCCESS,
            )
