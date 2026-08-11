from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0012_carvideo"),
        ("integrations", "0004_vehicle_publications_and_message_edits"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramoutboxmessage",
            name="media_object_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="telegramoutboxmessage",
            name="media_object_type",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AlterField(
            model_name="telegramoutboxmessage",
            name="operation",
            field=models.CharField(
                choices=[
                    ("send_message", "Send message"),
                    ("edit_message", "Edit message"),
                    ("send_photo", "Send photo"),
                    ("send_video", "Send video"),
                    ("answer_callback", "Answer callback"),
                ],
                default="send_message",
                max_length=30,
            ),
        ),
    ]
