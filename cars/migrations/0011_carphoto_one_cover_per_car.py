# Generated manually to normalize legacy cover flags before the constraint.

from django.db import migrations, models


def normalize_car_photo_covers(apps, schema_editor):
    """Keep the first ordered cover if a legacy car has several covers."""

    CarPhoto = apps.get_model("cars", "CarPhoto")
    previous_car_id = None

    for photo in CarPhoto.objects.filter(is_cover=True).order_by(
        "car_id",
        "sort_order",
        "pk",
    ):
        if photo.car_id == previous_car_id:
            photo.is_cover = False
            photo.save(update_fields=["is_cover"])
        else:
            previous_car_id = photo.car_id


class Migration(migrations.Migration):
    dependencies = [
        ("cars", "0010_vehicleinventoryevent"),
    ]

    operations = [
        migrations.RunPython(
            normalize_car_photo_covers,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="carphoto",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_cover", True)),
                fields=("car",),
                name="one_cover_photo_per_car",
            ),
        ),
    ]
