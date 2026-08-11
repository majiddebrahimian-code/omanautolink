from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cars", "0011_carphoto_one_cover_per_car"),
        ("integrations", "0003_telegramchannel_telegramintegrationsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramoutboxmessage",
            name="target_message_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="telegramoutboxmessage",
            name="operation",
            field=models.CharField(
                choices=[
                    ("send_message", "Send message"),
                    ("edit_message", "Edit message"),
                    ("answer_callback", "Answer callback"),
                ],
                default="send_message",
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="TelegramVehiclePublication",
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
                ("telegram_message_id", models.BigIntegerField(blank=True, null=True)),
                ("revision", models.PositiveIntegerField(default=0)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "car",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="telegram_publications",
                        to="cars.car",
                    ),
                ),
                (
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vehicle_publications",
                        to="integrations.telegramchannel",
                    ),
                ),
                (
                    "latest_outbox_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="vehicle_publications",
                        to="integrations.telegramoutboxmessage",
                    ),
                ),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.AddConstraint(
            model_name="telegramvehiclepublication",
            constraint=models.UniqueConstraint(
                fields=("car", "channel"),
                name="one_vehicle_post_per_channel",
            ),
        ),
        migrations.AddIndex(
            model_name="telegramvehiclepublication",
            index=models.Index(
                fields=["channel", "telegram_message_id"],
                name="tg_vehicle_channel_msg_idx",
            ),
        ),
    ]
