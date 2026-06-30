from django.contrib import admin
from .models import SiteSetting, OrderRequest, FaqCategory, FaqItem


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ["key", "value"]


@admin.register(OrderRequest)
class OrderRequestAdmin(admin.ModelAdmin):
    list_display = ["customer_name", "phone", "type", "status", "created_at"]
    list_filter = ["type", "status"]


class FaqItemInline(admin.TabularInline):
    model = FaqItem
    extra = 1


@admin.register(FaqCategory)
class FaqCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "emoji"]
    inlines = [FaqItemInline]
