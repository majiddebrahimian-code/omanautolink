import secrets

from django.db import migrations, models
from django.db.models import Q


def populate_vehicle_codes(apps, schema_editor):
    Car = apps.get_model("cars", "Car")
    for car in Car.objects.filter(Q(vehicle_code__isnull=True) | Q(vehicle_code="")).iterator():
        while True:
            code = f"CAR-{secrets.token_hex(4).upper()}"
            if not Car.objects.filter(vehicle_code=code).exists():
                car.vehicle_code = code
                car.save(update_fields=["vehicle_code"])
                break


class Migration(migrations.Migration):
    dependencies = [("cars", "0013_alter_car_options_alter_vehicleinventoryevent_action")]

    operations = [
        migrations.AddField(
            model_name="car",
            name="vehicle_code",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=24, null=True, unique=True),
        ),
        migrations.RunPython(populate_vehicle_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="car",
            name="vehicle_code",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=24, unique=True),
        ),
    ]