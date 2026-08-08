import tracking.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tracking", "0011_trackingimportjob_trackingimportrow"),
    ]

    operations = [
        migrations.AlterField(
            model_name="trackingimportjob",
            name="upload",
            field=models.FileField(upload_to=tracking.models.tracking_import_upload_to),
        ),
    ]
