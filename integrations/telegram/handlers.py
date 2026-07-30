"""Telegram-specific presentation and command routing.

This module does not update ``Car``, stage progress, or tracking events
directly.  It only invokes integration and tracking services.
"""

from django.core.exceptions import ValidationError

from integrations.services import (
    cancel_telegram_stage_confirmation_session,
    confirm_telegram_stage_confirmation_session,
    create_telegram_stage_confirmation_session,
    link_staff_telegram_account,
    queue_telegram_callback_ack,
    queue_telegram_message,
)

from . import messages


def _queue_reply(*, inbound_update, parsed, body, message_type, staff_link=None, reply_markup=None):
    return queue_telegram_message(
        chat_id=parsed["telegram_chat_id"],
        body=body,
        message_type=message_type,
        idempotency_key=f"telegram-update:{inbound_update.pk}:reply",
        reply_markup=reply_markup,
        reply_to_message_id=parsed["telegram_message_id"],
        inbound_update=inbound_update,
        staff_link=staff_link,
    )


def _handle_link_command(*, inbound_update, parsed):
    link_code = parsed["command_argument"]

    if not link_code:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.link_code_required_text(),
            message_type="link_code_required",
        )
        return

    try:
        staff_link = link_staff_telegram_account(
            code=link_code,
            telegram_user_id=parsed["telegram_user_id"],
            telegram_chat_id=parsed["telegram_chat_id"],
            telegram_username=parsed["telegram_username"],
            first_name=parsed["first_name"],
            last_name=parsed["last_name"],
        )
    except ValidationError:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.link_failed_text(),
            message_type="link_failed",
        )
        return

    inbound_update.staff_link = staff_link
    inbound_update.save(update_fields=["staff_link"])
    _queue_reply(
        inbound_update=inbound_update,
        parsed=parsed,
        body=messages.link_success_text(
            username=staff_link.first_name or staff_link.user.get_full_name()
        ),
        message_type="link_success",
        staff_link=staff_link,
    )


def _handle_confirm_command(*, inbound_update, parsed, staff_link):
    if staff_link is None:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.not_linked_text(),
            message_type="not_linked",
        )
        return

    tracking_code = parsed["command_argument"]

    if not tracking_code:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.tracking_code_required_text(),
            message_type="tracking_code_required",
            staff_link=staff_link,
        )
        return

    try:
        confirmation_session = create_telegram_stage_confirmation_session(
            staff_link=staff_link,
            tracking_code=tracking_code,
        )
    except ValidationError:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.confirmation_failed_text(),
            message_type="confirmation_preview_failed",
            staff_link=staff_link,
        )
        return

    _queue_reply(
        inbound_update=inbound_update,
        parsed=parsed,
        body=messages.confirmation_preview_text(
            car=confirmation_session.car,
            stage=confirmation_session.stage,
        ),
        message_type="confirmation_preview",
        staff_link=staff_link,
        reply_markup=messages.confirmation_markup(
            session_token=confirmation_session.public_token,
        ),
    )


def _handle_callback(*, inbound_update, parsed, staff_link):
    callback_query_id = str(parsed["callback_query_id"] or "")

    if staff_link is None:
        queue_telegram_callback_ack(
            callback_query_id=callback_query_id,
            body="دسترسی ندارید.",
            idempotency_key=f"telegram-update:{inbound_update.pk}:callback-ack",
            inbound_update=inbound_update,
        )
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.not_linked_text(),
            message_type="not_linked",
        )
        return

    action, separator, session_token = str(parsed["callback_data"] or "").partition(":")

    if not separator or action not in {"confirm", "cancel"} or not session_token:
        queue_telegram_callback_ack(
            callback_query_id=callback_query_id,
            body="درخواست نامعتبر است.",
            idempotency_key=f"telegram-update:{inbound_update.pk}:callback-ack",
            inbound_update=inbound_update,
            staff_link=staff_link,
        )
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.invalid_callback_text(),
            message_type="invalid_callback",
            staff_link=staff_link,
        )
        return

    if action == "cancel":
        try:
            cancel_telegram_stage_confirmation_session(
                staff_link=staff_link,
                public_token=session_token,
            )
        except ValidationError:
            callback_body = "لغو انجام نشد."
            reply_body = messages.confirmation_failed_text()
            reply_type = "confirmation_cancel_failed"
        else:
            callback_body = "لغو شد."
            reply_body = messages.confirmation_cancelled_text()
            reply_type = "confirmation_cancelled"

        queue_telegram_callback_ack(
            callback_query_id=callback_query_id,
            body=callback_body,
            idempotency_key=f"telegram-update:{inbound_update.pk}:callback-ack",
            inbound_update=inbound_update,
            staff_link=staff_link,
        )
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=reply_body,
            message_type=reply_type,
            staff_link=staff_link,
        )
        return

    try:
        result = confirm_telegram_stage_confirmation_session(
            staff_link=staff_link,
            public_token=session_token,
        )
    except ValidationError:
        callback_body = "تأیید انجام نشد."
        reply_body = messages.confirmation_failed_text()
        reply_type = "confirmation_failed"
    else:
        if result["already_confirmed"]:
            callback_body = "قبلاً تأیید شده است."
            reply_body = "این درخواست قبلاً تأیید شده است؛ تغییر تکراری ثبت نشد."
            reply_type = "confirmation_already_done"
        else:
            callback_body = "تأیید شد."
            reply_body = messages.confirmation_success_text(
                car=result["session"].car,
                stage=result["session"].stage,
            )
            reply_type = "confirmation_success"

    queue_telegram_callback_ack(
        callback_query_id=callback_query_id,
        body=callback_body,
        idempotency_key=f"telegram-update:{inbound_update.pk}:callback-ack",
        inbound_update=inbound_update,
        staff_link=staff_link,
    )
    _queue_reply(
        inbound_update=inbound_update,
        parsed=parsed,
        body=reply_body,
        message_type=reply_type,
        staff_link=staff_link,
    )


def handle_telegram_inbound_update(*, inbound_update, parsed, staff_link):
    """Routes a sanitized private Telegram update to a presentation action."""

    # Staff authentication is deliberately private-chat only.
    if parsed["chat_type"] != "private":
        return

    if parsed["update_type"] == "message":
        command = parsed["command_name"]

        if command in {"/start", "/link"}:
            if parsed["command_argument"]:
                _handle_link_command(
                    inbound_update=inbound_update,
                    parsed=parsed,
                )
            else:
                _queue_reply(
                    inbound_update=inbound_update,
                    parsed=parsed,
                    body=messages.staff_help_text(),
                    message_type="help",
                    staff_link=staff_link,
                )
            return

        if command == "/confirm":
            _handle_confirm_command(
                inbound_update=inbound_update,
                parsed=parsed,
                staff_link=staff_link,
            )
            return

        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.staff_help_text(),
            message_type="help",
            staff_link=staff_link,
        )
        return

    if parsed["update_type"] == "callback_query":
        _handle_callback(
            inbound_update=inbound_update,
            parsed=parsed,
            staff_link=staff_link,
        )

