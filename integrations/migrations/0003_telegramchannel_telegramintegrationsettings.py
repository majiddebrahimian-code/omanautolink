# Generated manually to keep the migration reviewable.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0002_customertelegramsubscription_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TelegramChannel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("chat_id", models.BigIntegerField(unique=True)),
                ("username", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("publish_available_vehicles", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name", "pk"], "verbose_name": "کانال Telegram", "verbose_name_plural": "کانال‌های Telegram"},
        ),
        migrations.CreateModel(
            name="TelegramIntegrationSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("inbound_mode", models.CharField(choices=[("webhook", "Webhook"), ("polling", "Long polling")], default="webhook", max_length=20)),
                ("customer_notifications_enabled", models.BooleanField(default=True)),
                ("staff_bot_enabled", models.BooleanField(default=True)),
                ("vehicle_channel_sync_enabled", models.BooleanField(default=False)),
                ("sold_vehicle_publication_action", models.CharField(choices=[("mark_sold", "Mark as sold"), ("delete", "Delete post")], default="mark_sold", max_length=20)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("default_vehicle_channel", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="default_for_settings", to="integrations.telegramchannel")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="updated_telegram_integration_settings", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "تنظیمات Telegram", "verbose_name_plural": "تنظیمات Telegram"},
        ),
    ]
