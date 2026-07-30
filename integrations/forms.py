from django import forms
from django.contrib.auth import get_user_model


class TelegramStaffLinkCodeForm(forms.Form):
    """System-administrator form for issuing a one-time Telegram link code."""

    staff_user = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        label="کارمند داخلی",
        help_text="کد اتصال فقط برای کارمند فعال و داخلی صادر می‌شود.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff_user"].queryset = get_user_model().objects.filter(
            is_active=True,
            is_staff=True,
        ).order_by("username")
