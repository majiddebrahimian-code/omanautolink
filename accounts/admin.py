from django.contrib import admin
from .models import StaffManagementEvent, StaffProfile


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "phone"]
    filter_horizontal = ["assigned_stages"]


@admin.register(StaffManagementEvent)
class StaffManagementEventAdmin(admin.ModelAdmin):
    list_display = ["staff_user", "action", "performed_by", "source", "created_at"]
    list_filter = ["action", "source"]
    search_fields = [
        "staff_user__username",
        "staff_user__first_name",
        "staff_user__last_name",
        "performed_by__username",
    ]
    readonly_fields = [
        "staff_user",
        "performed_by",
        "action",
        "changes",
        "source",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
