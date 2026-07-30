from django.urls import path

from .views import telegram_webhook


app_name = "integrations"

urlpatterns = [
    path("telegram/webhook/", telegram_webhook, name="telegram_webhook"),
]
