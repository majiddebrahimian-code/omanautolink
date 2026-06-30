from django.contrib import admin
from .models import Stage, CarStageProgress


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ['name', 'order', 'default_duration_days', 'is_active']
    list_editable = ['order', 'default_duration_days', 'is_active']
    ordering = ['order']


@admin.register(CarStageProgress)
class CarStageProgressAdmin(admin.ModelAdmin):
    list_display = ['car', 'stage', 'planned_date', 'actual_arrival', 'confirmed_by']
    list_filter = ['stage']