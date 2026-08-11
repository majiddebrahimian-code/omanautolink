from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0011_carphoto_one_cover_per_car"),
    ]

    operations = [
        migrations.CreateModel(
            name="CarVideo",
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
                    "video",
                    models.FileField(
                        upload_to="cars/videos/",
                        validators=[django.core.validators.FileExtensionValidator(["mp4", "mov", "webm"])],
                    ),
                ),
                ("telegram_file_id", models.CharField(blank=True, max_length=200, null=True)),
                ("caption", models.CharField(blank=True, max_length=250)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "car",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="videos",
                        to="cars.car",
                    ),
                ),
            ],
            options={"ordering": ["sort_order", "pk"]},
        ),
    ]
