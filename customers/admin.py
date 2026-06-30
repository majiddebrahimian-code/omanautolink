from django.contrib import admin
from .models import Customer, SearchLog


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["full_name", "phone", "telegram_id"]
    search_fields = ["full_name", "phone"]


@admin.register(SearchLog)
class SearchLogAdmin(admin.ModelAdmin):
    list_display = ["source", "car", "customer", "searched_at"]
    list_filter = ["source"]
