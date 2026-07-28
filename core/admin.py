from django.contrib import admin

from .models import FaqCategory, FaqItem, SiteSetting


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ["key", "value"]


class FaqItemInline(admin.TabularInline):
    model = FaqItem
    extra = 1


@admin.register(FaqCategory)
class FaqCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "emoji"]
    inlines = [FaqItemInline]
