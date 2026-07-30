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


def general_help_text():
    return (
        "سلام. به ربات عمان اتولینک خوش آمدید.\n\n"
        "مشتری: برای مشاهدهٔ رهگیری، «/track کد-رهگیری» را وارد کنید. "
        "اگر پس از فروش کد فعال‌سازی دریافت کرده‌اید، آن را به شکل "
        "«/start TGC-...» بفرستید تا اعلان‌های خودرو فعال شود.\n\n"
        "کارکنان داخلی: برای اتصال حساب، «/start TGL-...» و برای تأیید "
        "مرحله، «/confirm کد-رهگیری» را وارد کنید."
    )


def customer_activation_code_required_text():
    return (
        "برای فعال‌سازی اعلان‌های رهگیری، کدی را که پس از فروش از مشاور "
        "دریافت کرده‌اید وارد کنید. نمونه: «/start TGC-...»"
    )


def customer_activation_failed_text():
    return (
        "کد فعال‌سازی معتبر نیست، منقضی شده یا قبلاً استفاده شده است. "
        "برای دریافت کد جدید با مشاور خود تماس بگیرید."
    )


def customer_tracking_code_required_text(*, command="/track"):
    return (
        f"کد رهگیری را وارد کنید. نمونه: «{command} OAL-...»"
    )


def customer_tracking_not_found_text():
    # Keep this generic: a caller must not learn whether a code ever existed.
    return "اطلاعات رهگیری با این کد پیدا نشد."


def customer_tracking_rate_limited_text():
    return (
        "تعداد تلاش‌های شما بیش از حد مجاز است. لطفاً چند دقیقهٔ دیگر "
        "دوباره تلاش کنید."
    )


def customer_no_active_subscription_text():
    return (
        "برای این حساب تلگرام، اعلان فعالِ خودرو پیدا نشد. "
        "می‌توانید با «/track کد-رهگیری» وضعیت خودرو را ببینید."
    )


def customer_stop_success_text(*, tracking_code):
    return (
        f"ارسال اعلان‌های تلگرام برای خودروی دارای کد {tracking_code} "
        "متوقف شد. برای فعال‌سازی دوباره، از مشاور کد جدید دریافت کنید."
    )


def customer_stop_failed_text():
    return (
        "اشتراک فعال برای این کد رهگیری در این حساب تلگرام پیدا نشد."
    )


def _stage_state_text(state):
    return {
        "pending": "در انتظار ورود",
        "entered": "وارد شده",
        "completed": "تکمیل شده",
        "skipped": "رد شده",
    }.get(state, "نامشخص")


def _eta_text(remaining_eta_days):
    if remaining_eta_days is None:
        return "زمان تقریبی باقی‌مانده: در حال به‌روزرسانی"

    if remaining_eta_days == 0:
        return "زمان تقریبی باقی‌مانده: مرحلهٔ پایانی"

    return f"زمان تقریبی باقی‌مانده: {remaining_eta_days} روز"


def _customer_tracking_snapshot_text(*, tracking_data, include_heading=True):
    vehicle = tracking_data["vehicle"]
    current_stage = tracking_data["current_stage"]
    heading = "وضعیت رهگیری خودرو\n\n" if include_heading else ""
    current_stage_text = (
        f"{current_stage['name']} ({_stage_state_text(current_stage['state'])})"
        if current_stage
        else "در حال آماده‌سازی"
    )

    stage_lines = [
        f"• {stage['name']}: {_stage_state_text(stage['state'])}"
        for stage in tracking_data["stages"]
    ]

    return (
        f"{heading}"
        f"خودرو: {vehicle['title']}\n"
        f"کد رهگیری: {tracking_data['tracking_code']}\n"
        f"مرحلهٔ فعلی: {current_stage_text}\n"
        f"{_eta_text(tracking_data['remaining_eta_days'])}\n\n"
        "تاریخچهٔ مراحل:\n"
        + "\n".join(stage_lines)
    )


def customer_activation_success_text(*, tracking_data):
    return (
        "اعلان‌های تلگرام این خودرو با موفقیت فعال شد. از این پس، تغییرات "
        "مهم رهگیری برای شما ارسال می‌شود.\n\n"
        + _customer_tracking_snapshot_text(tracking_data=tracking_data)
    )


def customer_tracking_lookup_text(*, tracking_data):
    return _customer_tracking_snapshot_text(tracking_data=tracking_data)


def customer_subscriptions_status_text(*, tracking_data_items):
    return "\n\n".join(
        _customer_tracking_snapshot_text(
            tracking_data=tracking_data,
            include_heading=index == 0,
        )
        for index, tracking_data in enumerate(tracking_data_items)
    )


def customer_tracking_notification_text(*, snapshot):
    event_text = {
        "stage_confirmed": "خودرو وارد مرحلهٔ جدید شد",
        "stage_completed": "یک مرحله از رهگیری تکمیل شد",
        "stage_corrected": "وضعیت رهگیری اصلاح شد",
        "stage_skipped": "یک مرحله از رهگیری رد شد",
        "stage_archived": "مسیر رهگیری به‌روزرسانی شد",
    }.get(snapshot["event_type"], "وضعیت رهگیری به‌روزرسانی شد")

    stage_name = (
        snapshot["new_stage_name"]
        or snapshot["current_stage_name"]
        or "در حال به‌روزرسانی"
    )

    return (
        f"{event_text}.\n\n"
        f"خودرو: {snapshot['vehicle_title']}\n"
        f"کد رهگیری: {snapshot['tracking_code']}\n"
        f"مرحلهٔ فعلی: {stage_name}\n"
        f"{_eta_text(snapshot['remaining_eta_days'])}\n\n"
        "برای مشاهدهٔ تاریخچهٔ کامل، «/status» یا «/track کد-رهگیری» را وارد کنید."
    )
