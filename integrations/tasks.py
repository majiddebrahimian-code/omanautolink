from celery import shared_task

from .services import (
    deliver_telegram_outbox_message,
    get_due_telegram_outbox_message_ids,
)


@shared_task(name="integrations.deliver_telegram_outbox_message")
def deliver_telegram_outbox_message_task(outbox_id):
    """Delivers one durable outbox message and schedules a bounded retry."""

    result = deliver_telegram_outbox_message(outbox_id=outbox_id)

    if result.get("outcome") == "retry":
        deliver_telegram_outbox_message_task.apply_async(
            args=[outbox_id],
            countdown=result["countdown_seconds"],
        )

    return result


@shared_task(name="integrations.process_due_telegram_outbox_messages")
def process_due_telegram_outbox_messages_task(limit=100):
    """Periodic recovery for queued/retry/stale Telegram outbound work."""

    outbox_ids = get_due_telegram_outbox_message_ids(limit=limit)

    for outbox_id in outbox_ids:
        deliver_telegram_outbox_message_task.delay(outbox_id)

    return len(outbox_ids)
