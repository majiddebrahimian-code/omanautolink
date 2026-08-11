"""Small Telegram Bot API gateway using only Python's standard library."""

import json
import socket
import uuid
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

    def _multipart_request(self, *, method, fields, files):
        if not settings.TELEGRAM_BOT_ENABLED or not self.token:
            raise TelegramGatewayPermanentError("Telegram bot is not configured.")

        boundary = f"----OmanAutoLink{uuid.uuid4().hex}"
        parts = []
        for name, value in fields.items():
            if value is None:
                continue
            parts.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ])
        for file_item in files:
            parts.extend([
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{file_item["field_name"]}"; '
                    f'filename="{file_item["file_name"]}"\r\n'
                ).encode(),
                f"Content-Type: {file_item['content_type']}\r\n\r\n".encode(),
                file_item["file_data"],
                b"\r\n",
            ])
        parts.append(f"--{boundary}--\r\n".encode())
        http_request = request.Request(
            url=f"{self.API_BASE_URL}/bot{self.token}/{method}",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=settings.TELEGRAM_HTTP_TIMEOUT_SECONDS) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as http_error:
            if http_error.code == 429 or 500 <= http_error.code <= 599:
                raise TelegramGatewayTransientError("Telegram HTTP error.")
            raise TelegramGatewayPermanentError("Telegram HTTP error.")
        except (error.URLError, socket.timeout, TimeoutError, json.JSONDecodeError):
            raise TelegramGatewayTransientError("Telegram network error.")

        if not isinstance(response_data, dict) or response_data.get("ok") is not True:
            error_code = response_data.get("error_code") if isinstance(response_data, dict) else None
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

    def edit_message_text(
        self,
        *,
        chat_id,
        message_id,
        text,
        reply_markup=None,
    ):
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }

        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        return self._request(method="editMessageText", payload=payload)

    def send_photo(self, *, chat_id, file_name, file_data, content_type, caption=""):
        return self._multipart_request(
            method="sendPhoto",
            fields={"chat_id": chat_id, "caption": caption},
            files=[{
                "field_name": "photo",
                "file_name": file_name,
                "file_data": file_data,
                "content_type": content_type,
            }],
        )

    def send_video(self, *, chat_id, file_name, file_data, content_type, caption=""):
        return self._multipart_request(
            method="sendVideo",
            fields={"chat_id": chat_id, "caption": caption},
            files=[{
                "field_name": "video",
                "file_name": file_name,
                "file_data": file_data,
                "content_type": content_type,
            }],
        )

    def send_media_group(self, *, chat_id, media_items, caption=""):
        """Send a Telegram album; its caption belongs to the first media item."""
        media = []
        files = []
        for index, item in enumerate(media_items):
            field_name = f"media{index}"
            payload = {
                "type": item["kind"],
                "media": f"attach://{field_name}",
            }
            if index == 0 and caption:
                payload["caption"] = caption
            media.append(payload)
            files.append({
                "field_name": field_name,
                "file_name": item["file_name"],
                "file_data": item["file_data"],
                "content_type": item["content_type"],
            })
        return self._multipart_request(
            method="sendMediaGroup",
            fields={"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)},
            files=files,
        )

    def edit_message_caption(self, *, chat_id, message_id, caption):
        return self._request(
            method="editMessageCaption",
            payload={
                "chat_id": chat_id,
                "message_id": message_id,
                "caption": caption,
            },
        )

    def delete_message(self, *, chat_id, message_id):
        return self._request(
            method="deleteMessage",
            payload={
                "chat_id": chat_id,
                "message_id": message_id,
            },
        )

    def get_me(self):
        """Return the configured Bot's public identity without exposing its token."""
        return self._request(method="getMe", payload={})

    def get_chat(self, *, chat_id):
        return self._request(method="getChat", payload={"chat_id": chat_id})

    def get_chat_member(self, *, chat_id, user_id):
        return self._request(
            method="getChatMember",
            payload={"chat_id": chat_id, "user_id": user_id},
        )

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
