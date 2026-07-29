from django.contrib import admin

from .models import CarStageProgress, Stage


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "order",
        "default_duration_days",
        "is_active",
    ]
    search_fields = ["name"]
    ordering = ["order"]

    # Deactivation must go through archive_stage, not direct editing.
    readonly_fields = ["is_active"]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CarStageProgress)
class CarStageProgressAdmin(admin.ModelAdmin):
    list_display = [
        "car",
        "stage",
        "state",
        "planned_date",
        "actual_arrival",
        "confirmed_by",
        "completed_at",
        "completed_by",
        "skipped_at",
        "skipped_by",
    ]
    list_filter = ["stage"]
    search_fields = [
        "car__tracking_code",
        "car__title",
        "stage__name",
    ]
    list_select_related = [
        "car",
        "stage",
        "confirmed_by",
        "completed_by",
        "skipped_by",
    ]

    readonly_fields = [
        "car",
        "stage",
        "planned_date",
        "actual_arrival",
        "confirmed_by",
        "completed_at",
        "completed_by",
        "skipped_at",
        "skipped_by",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
