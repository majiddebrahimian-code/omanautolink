# Generated manually for the staff-management audit feature.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffManagementEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("created", "Employee created"),
                            ("updated", "Employee updated"),
                            ("password_reset", "Password reset"),
                            ("deactivated", "Employee deactivated"),
                            ("reactivated", "Employee reactivated"),
                            ("telegram_link_issued", "Telegram link issued"),
                            ("telegram_link_revoked", "Telegram link revoked"),
                        ],
                        max_length=40,
                    ),
                ),
                ("changes", models.JSONField(blank=True, default=dict)),
                (
                    "source",
                    models.CharField(
                        choices=[("backoffice", "Backoffice"), ("system", "System")],
                        default="backoffice",
                        max_length=30,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "performed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="performed_staff_management_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "staff_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="staff_management_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "رویداد مدیریت کارمند",
                "verbose_name_plural": "رویدادهای مدیریت کارکنان",
                "ordering": ["-created_at", "-pk"],
                "indexes": [
                    models.Index(
                        fields=["staff_user", "created_at"],
                        name="staff_mgmt_evt_user_ts_idx",
                    )
                ],
            },
        ),
    ]
