"""Persian text and small presentation helpers for the staff Telegram bot."""


def staff_help_text():
    return (
        "سلام. این رباتِ عملیاتی عمان اتولینک برای کارکنان داخلی است.\n\n"
        "۱. ابتدا کد اتصال یک‌بارمصرفی را که مدیر سیستم صادر کرده است، با این "
        "دستور وارد کنید:\n"
        "«/start TGL-...»\n\n"
        "۲. برای مشاهده و تأیید مرحلهٔ بعدی یک خودرو بنویسید:\n"
        "«/confirm OAL-...»\n\n"
        "تأیید نهایی فقط پس از بررسی مرحلهٔ مورد انتظار و دسترسی شما انجام می‌شود."
    )


def link_code_required_text():
    return (
        "برای اتصال حساب کارمندی، کد یک‌بارمصرف مدیر را وارد کنید.\n"
        "نمونه: «/start TGL-...»"
    )


def link_success_text(*, username):
    display_name = username or "کارمند گرامی"
    return (
        f"{display_name}، اتصال امن حساب تلگرام شما با موفقیت ثبت شد.\n\n"
        "از این پس می‌توانید با دستور `/confirm کد-رهگیری` مرحلهٔ بعدی خودرو را "
        "بررسی و تأیید کنید."
    )


def link_failed_text():
    return "کد اتصال معتبر نیست، منقضی شده است یا قبلاً استفاده شده است."


def not_linked_text():
    return (
        "حساب تلگرام شما به یک کارمند داخلی متصل نشده است. "
        "برای دریافت کد اتصال با مدیر اصلی سیستم تماس بگیرید."
    )


def tracking_code_required_text():
    return "کد رهگیری را وارد کنید. نمونه: «/confirm OAL-...»"


def confirmation_preview_text(*, car, stage):
    return (
        "لطفاً اطلاعات زیر را بررسی کنید:\n\n"
        f"خودرو: {car.title}\n"
        f"کد رهگیری: {car.tracking_code}\n"
        f"مرحلهٔ مورد انتظار: {stage.name}\n\n"
        "با انتخاب «تأیید مرحله»، ورود خودرو به این مرحله ثبت می‌شود."
    )


def confirmation_markup(*, session_token):
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ تأیید مرحله",
                    "callback_data": f"confirm:{session_token}",
                },
                {
                    "text": "❌ لغو",
                    "callback_data": f"cancel:{session_token}",
                },
            ]
        ]
    }


def confirmation_success_text(*, car, stage):
    return (
        "تأیید مرحله با موفقیت ثبت شد.\n\n"
        f"خودرو: {car.title}\n"
        f"کد رهگیری: {car.tracking_code}\n"
        f"مرحلهٔ ثبت‌شده: {stage.name}"
    )


def confirmation_cancelled_text():
    return "درخواست تأیید مرحله لغو شد؛ هیچ تغییری در وضعیت خودرو ایجاد نشد."


def confirmation_failed_text():
    return (
        "تأیید مرحله انجام نشد. ممکن است وضعیت خودرو تغییر کرده باشد، مرحلهٔ "
        "دیگری در انتظار باشد یا دسترسی شما کافی نباشد."
    )


def invalid_callback_text():
    return "این دکمه معتبر نیست یا دیگر قابل استفاده نیست."
