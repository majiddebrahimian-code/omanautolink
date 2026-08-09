"""Telegram-specific presentation and command routing.

This adapter never changes a ``Car`` or tracking progress directly.  It routes
commands to shared services, which makes Website, Django Admin, Excel import,
and Telegram follow the same business rules.
"""

from django.core.exceptions import ValidationError

from integrations.services import (
    activate_customer_telegram_tracking,
    cancel_telegram_stage_confirmation_session,
    confirm_telegram_stage_confirmation_session,
    create_telegram_stage_confirmation_session,
    get_active_customer_telegram_subscriptions,
    get_customer_bot_tracking_data,
    get_telegram_integration_settings,
    is_telegram_tracking_lookup_allowed,
    link_staff_telegram_account,
    queue_telegram_callback_ack,
    queue_telegram_message,
    unsubscribe_customer_telegram_tracking,
)

from . import messages


def _queue_reply(
    *,
    inbound_update,
    parsed,
    body,
    message_type,
    staff_link=None,
    customer_subscription=None,
    reply_markup=None,
):
    return queue_telegram_message(
        chat_id=parsed["telegram_chat_id"],
        body=body,
        message_type=message_type,
        idempotency_key=f"telegram-update:{inbound_update.pk}:reply",
        reply_markup=reply_markup,
        reply_to_message_id=parsed["telegram_message_id"],
        inbound_update=inbound_update,
        staff_link=staff_link,
        customer_subscription=customer_subscription,
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


def _handle_customer_activation(*, inbound_update, parsed):
    activation_code = parsed["command_argument"]

    if not activation_code:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_activation_code_required_text(),
            message_type="customer_activation_code_required",
        )
        return

    try:
        subscription = activate_customer_telegram_tracking(
            code=activation_code,
            telegram_user_id=parsed["telegram_user_id"],
            telegram_chat_id=parsed["telegram_chat_id"],
            telegram_username=parsed["telegram_username"],
            first_name=parsed["first_name"],
            last_name=parsed["last_name"],
        )
        tracking_data = get_customer_bot_tracking_data(
            tracking_code=subscription.car.tracking_code,
        )
    except ValidationError:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_activation_failed_text(),
            message_type="customer_activation_failed",
        )
        return

    inbound_update.customer_subscription = subscription
    inbound_update.save(update_fields=["customer_subscription"])
    _queue_reply(
        inbound_update=inbound_update,
        parsed=parsed,
        body=messages.customer_activation_success_text(tracking_data=tracking_data),
        message_type="customer_activation_success",
        customer_subscription=subscription,
    )


def _handle_customer_tracking_lookup(
    *,
    inbound_update,
    parsed,
    customer_subscription,
):
    tracking_code = parsed["command_argument"]

    if not tracking_code:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_tracking_code_required_text(),
            message_type="customer_tracking_code_required",
            customer_subscription=customer_subscription,
        )
        return

    if not is_telegram_tracking_lookup_allowed(
        telegram_user_id=parsed["telegram_user_id"],
        telegram_chat_id=parsed["telegram_chat_id"],
    ):
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_tracking_rate_limited_text(),
            message_type="customer_tracking_rate_limited",
            customer_subscription=customer_subscription,
        )
        return

    try:
        tracking_data = get_customer_bot_tracking_data(
            tracking_code=tracking_code,
        )
    except ValidationError:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_tracking_not_found_text(),
            message_type="customer_tracking_not_found",
            customer_subscription=customer_subscription,
        )
        return

    _queue_reply(
        inbound_update=inbound_update,
        parsed=parsed,
        body=messages.customer_tracking_lookup_text(tracking_data=tracking_data),
        message_type="customer_tracking_lookup",
        customer_subscription=customer_subscription,
    )


def _handle_customer_status(*, inbound_update, parsed, customer_subscription):
    try:
        subscriptions = get_active_customer_telegram_subscriptions(
            telegram_user_id=parsed["telegram_user_id"],
            telegram_chat_id=parsed["telegram_chat_id"],
        )
    except ValidationError:
        subscriptions = []

    if not subscriptions:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_no_active_subscription_text(),
            message_type="customer_no_active_subscription",
            customer_subscription=customer_subscription,
        )
        return

    tracking_data_items = []
    for subscription in subscriptions[:5]:
        try:
            tracking_data_items.append(
                get_customer_bot_tracking_data(
                    tracking_code=subscription.car.tracking_code,
                )
            )
        except ValidationError:
            # A historical subscription should never prevent other eligible
            # vehicles from being shown to the same verified Telegram account.
            continue

    if not tracking_data_items:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_no_active_subscription_text(),
            message_type="customer_no_active_subscription",
            customer_subscription=customer_subscription,
        )
        return

    _queue_reply(
        inbound_update=inbound_update,
        parsed=parsed,
        body=messages.customer_subscriptions_status_text(
            tracking_data_items=tracking_data_items,
        ),
        message_type="customer_tracking_status",
        customer_subscription=customer_subscription or subscriptions[0],
    )


def _handle_customer_stop(*, inbound_update, parsed, customer_subscription):
    tracking_code = parsed["command_argument"]

    if not tracking_code:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_tracking_code_required_text(command="/stop"),
            message_type="customer_stop_code_required",
            customer_subscription=customer_subscription,
        )
        return

    try:
        subscription = unsubscribe_customer_telegram_tracking(
            tracking_code=tracking_code,
            telegram_user_id=parsed["telegram_user_id"],
            telegram_chat_id=parsed["telegram_chat_id"],
        )
    except ValidationError:
        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.customer_stop_failed_text(),
            message_type="customer_stop_failed",
            customer_subscription=customer_subscription,
        )
        return

    if inbound_update.customer_subscription_id == subscription.pk:
        inbound_update.customer_subscription = None
        inbound_update.save(update_fields=["customer_subscription"])

    _queue_reply(
        inbound_update=inbound_update,
        parsed=parsed,
        body=messages.customer_stop_success_text(
            tracking_code=subscription.car.tracking_code,
        ),
        message_type="customer_stop_success",
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


def handle_telegram_inbound_update(
    *,
    inbound_update,
    parsed,
    staff_link,
    customer_subscription=None,
):
    """Routes a sanitized private Telegram update to staff or customer actions."""

    # Both staff authentication and customer activation are private-chat only.
    if parsed["chat_type"] != "private":
        return

    if parsed["update_type"] == "message":
        command = parsed["command_name"]
        command_argument = parsed["command_argument"]

        if command == "/start":
            if command_argument.startswith("TGL-"):
                _handle_link_command(
                    inbound_update=inbound_update,
                    parsed=parsed,
                )
            elif command_argument.startswith("TGC-"):
                _handle_customer_activation(
                    inbound_update=inbound_update,
                    parsed=parsed,
                )
            else:
                _queue_reply(
                    inbound_update=inbound_update,
                    parsed=parsed,
                    body=(
                        messages.general_help_text()
                        if not command_argument
                        else messages.customer_activation_failed_text()
                    ),
                    message_type=("help" if not command_argument else "start_invalid"),
                    staff_link=staff_link,
                    customer_subscription=customer_subscription,
                )
            return

        if command == "/link":
            _handle_link_command(
                inbound_update=inbound_update,
                parsed=parsed,
            )
            return

        if command == "/confirm":
            if not get_telegram_integration_settings().staff_bot_enabled:
                _queue_reply(
                    inbound_update=inbound_update,
                    parsed=parsed,
                    body="عملیات کارمندان در Bot موقتاً غیرفعال است.",
                    message_type="staff_bot_disabled",
                    staff_link=staff_link,
                )
                return
            _handle_confirm_command(
                inbound_update=inbound_update,
                parsed=parsed,
                staff_link=staff_link,
            )
            return

        if command == "/track":
            _handle_customer_tracking_lookup(
                inbound_update=inbound_update,
                parsed=parsed,
                customer_subscription=customer_subscription,
            )
            return

        if command == "/status":
            _handle_customer_status(
                inbound_update=inbound_update,
                parsed=parsed,
                customer_subscription=customer_subscription,
            )
            return

        if command == "/stop":
            _handle_customer_stop(
                inbound_update=inbound_update,
                parsed=parsed,
                customer_subscription=customer_subscription,
            )
            return

        _queue_reply(
            inbound_update=inbound_update,
            parsed=parsed,
            body=messages.general_help_text(),
            message_type="help",
            staff_link=staff_link,
            customer_subscription=customer_subscription,
        )
        return

    if parsed["update_type"] == "callback_query":
        _handle_callback(
            inbound_update=inbound_update,
            parsed=parsed,
            staff_link=staff_link,
        )
