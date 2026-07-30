import json
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    JsonResponse,
)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import ingest_and_process_telegram_update


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Receives a Telegram webhook and forwards it to the shared ingestion service."""

    if not settings.TELEGRAM_BOT_ENABLED:
        return HttpResponseNotFound()

    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET
    supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")

    if not expected_secret or not secrets.compare_digest(
        str(expected_secret),
        str(supplied_secret),
    ):
        return HttpResponseForbidden()

    # Telegram updates are small. This protects the public endpoint from oversized input.
    if len(request.body) > 1024 * 1024:
        return HttpResponseBadRequest("Payload is too large.")

    try:
        update = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponseBadRequest("Invalid JSON payload.")

    try:
        result = ingest_and_process_telegram_update(update=update)
    except ValidationError:
        return HttpResponseBadRequest("Invalid Telegram update.")
    except Exception:
        # The service writes a sanitized audit receipt and its own safe log entry.
        return JsonResponse({"ok": False}, status=500)

    return JsonResponse(
        {
            "ok": True,
            "duplicate": result["duplicate"],
        }
    )
