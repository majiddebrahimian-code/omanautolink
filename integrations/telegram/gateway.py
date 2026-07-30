"""Small Telegram Bot API gateway using only Python's standard library."""

import json
import socket
from urllib import error, request

from django.conf import settings


class TelegramGatewayError(Exception):
    """Base exception for a safe, transport-level Telegram failure."""


class TelegramGatewayTransientError(TelegramGatewayError):
    """A retryable network, rate-limit, or 5xx error."""


class TelegramGatewayPermanentError(TelegramGatewayError):
    """A configuration or non-retryable Telegram API error."""


class TelegramHTTPGateway:
    """Calls Telegram only after an outbox worker claims a message."""

    API_BASE_URL = "https://api.telegram.org"

    def __init__(self, *, token=None):
        self.token = settings.TELEGRAM_BOT_TOKEN if token is None else token

    def _request(self, *, method, payload, timeout=None):
        if not settings.TELEGRAM_BOT_ENABLED or not self.token:
            raise TelegramGatewayPermanentError("Telegram bot is not configured.")

        encoded_payload = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        http_request = request.Request(
            url=f"{self.API_BASE_URL}/bot{self.token}/{method}",
            data=encoded_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(
                http_request,
                timeout=timeout or settings.TELEGRAM_HTTP_TIMEOUT_SECONDS,
            ) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as http_error:
            if http_error.code == 429 or 500 <= http_error.code <= 599:
                raise TelegramGatewayTransientError("Telegram HTTP error.")
            raise TelegramGatewayPermanentError("Telegram HTTP error.")
        except (error.URLError, socket.timeout, TimeoutError, json.JSONDecodeError):
            raise TelegramGatewayTransientError("Telegram network error.")

        if not isinstance(response_data, dict):
            raise TelegramGatewayTransientError("Telegram response is invalid.")

        if response_data.get("ok") is not True:
            error_code = response_data.get("error_code")
            if error_code == 429 or (isinstance(error_code, int) and error_code >= 500):
                raise TelegramGatewayTransientError("Telegram API rejected the request.")
            raise TelegramGatewayPermanentError("Telegram API rejected the request.")

        return response_data.get("result")

    def send_message(
        self,
        *,
        chat_id,
        text,
        reply_markup=None,
        reply_to_message_id=None,
    ):
        payload = {
            "chat_id": chat_id,
            "text": text,
        }

        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id

        return self._request(method="sendMessage", payload=payload)

    def answer_callback_query(self, *, callback_query_id, text=""):
        return self._request(
            method="answerCallbackQuery",
            payload={
                "callback_query_id": callback_query_id,
                "text": text[:200],
            },
        )

    def get_updates(self, *, offset=None, timeout=None):
        poll_timeout = (
            settings.TELEGRAM_POLL_TIMEOUT_SECONDS if timeout is None else int(timeout)
        )
        payload = {
            "timeout": poll_timeout,
            "allowed_updates": ["message", "callback_query"],
        }

        if offset is not None:
            payload["offset"] = int(offset)

        result = self._request(
            method="getUpdates",
            payload=payload,
            # Long polling waits server-side, so the local timeout needs headroom.
            timeout=max(settings.TELEGRAM_HTTP_TIMEOUT_SECONDS, poll_timeout + 10),
        )

        if not isinstance(result, list):
            raise TelegramGatewayTransientError("Telegram updates response is invalid.")

        return result
