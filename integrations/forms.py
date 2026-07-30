from django import forms
from django.contrib.auth import get_user_model

from cars.models import Car


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


class TelegramCustomerActivationCodeForm(forms.Form):
    """Authorized sales staff can issue/reissue a one-time customer code."""

    car = forms.ModelChoiceField(
        queryset=Car.objects.none(),
        label="خودروی فروخته‌شده",
        help_text=(
            "فقط برای خودروی فروخته‌شده و دارای مشتری کد فعال‌سازی صادر "
            "می‌شود. صدور کد جدید، کدهای استفاده‌نشدهٔ قبلی را باطل می‌کند."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["car"].queryset = (
            Car.objects.select_related("customer")
            .filter(
                is_deleted=False,
                customer__isnull=False,
                status__in=[
                    Car.Status.SOLD,
                    Car.Status.IN_TRANSIT,
                    Car.Status.DELIVERED,
                ],
            )
            .order_by("-created_at")
        )
