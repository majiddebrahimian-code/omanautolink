import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from integrations.services import ingest_and_process_telegram_update
from integrations.telegram.gateway import (
    TelegramGatewayPermanentError,
    TelegramGatewayTransientError,
    TelegramHTTPGateway,
)


class Command(BaseCommand):
    help = (
        "Runs the Telegram long-polling adapter. Use only one polling process "
        "per bot token; production should normally use the protected webhook."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Fetch and process one batch, then exit.",
        )

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_ENABLED or not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError(
                "Telegram is disabled. Configure local .env before starting polling."
            )

        gateway = TelegramHTTPGateway()
        offset = None

        self.stdout.write("Telegram polling adapter started.")

        try:
            while True:
                try:
                    updates = gateway.get_updates(offset=offset)
                except TelegramGatewayPermanentError:
                    raise CommandError("Telegram polling stopped because configuration is invalid.")
                except TelegramGatewayTransientError:
                    self.stderr.write("Temporary Telegram connection error; retrying shortly.")
                    time.sleep(5)
                    continue

                for update in updates:
                    update_id = update.get("update_id") if isinstance(update, dict) else None

                    try:
                        ingest_and_process_telegram_update(update=update)
                    except Exception:
                        # The ingestion service stores a sanitized failed receipt.
                        self.stderr.write("One Telegram update could not be processed.")

                    if isinstance(update_id, int):
                        offset = update_id + 1

                if options["once"]:
                    break
        except KeyboardInterrupt:
            self.stdout.write("Telegram polling adapter stopped.")
