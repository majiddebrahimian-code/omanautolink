# Generated manually for the durable spreadsheet-import workflow.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tracking", "0010_alter_trackingevent_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="TrackingImportJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("upload", models.FileField(upload_to="tracking/imports/%Y/%m")),
                ("original_filename", models.CharField(max_length=255)),
                ("status", models.CharField(choices=[("queued", "در صف پردازش"), ("processing", "در حال پردازش"), ("completed", "تکمیل‌شده"), ("completed_with_errors", "تکمیل‌شده با خطا"), ("failed", "ناموفق")], default="queued", max_length=30)),
                ("total_rows", models.PositiveIntegerField(default=0)),
                ("success_count", models.PositiveIntegerField(default=0)),
                ("error_count", models.PositiveIntegerField(default=0)),
                ("failure_reason", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tracking_import_jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-pk"], "permissions": [("view_tracking_import_job", "Can view tracking spreadsheet imports")]},
        ),
        migrations.CreateModel(
            name="TrackingImportRow",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("row_number", models.PositiveIntegerField()),
                ("tracking_code", models.CharField(blank=True, max_length=40)),
                ("stage_name", models.CharField(blank=True, max_length=120)),
                ("outcome", models.CharField(choices=[("success", "ثبت شد"), ("error", "خطا")], max_length=10)),
                ("message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rows", to="tracking.trackingimportjob")),
            ],
            options={"ordering": ["row_number", "pk"]},
        ),
        migrations.AddIndex(
            model_name="trackingimportjob",
            index=models.Index(fields=["status", "created_at"], name="track_import_status_ts_idx"),
        ),
        migrations.AddConstraint(
            model_name="trackingimportrow",
            constraint=models.UniqueConstraint(fields=("job", "row_number"), name="unique_tracking_import_job_row"),
        ),
    ]
