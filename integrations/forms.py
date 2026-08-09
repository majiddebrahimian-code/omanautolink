from django import forms

from .models import TelegramChannel, TelegramIntegrationSettings


class TelegramIntegrationSettingsForm(forms.ModelForm):
    class Meta:
        model = TelegramIntegrationSettings
        fields = [
            "inbound_mode",
            "staff_bot_enabled",
            "customer_notifications_enabled",
            "vehicle_channel_sync_enabled",
            "default_vehicle_channel",
            "sold_vehicle_publication_action",
        ]
        widgets = {
            "inbound_mode": forms.Select(attrs={"class": "backoffice-select"}),
            "default_vehicle_channel": forms.Select(attrs={"class": "backoffice-select"}),
            "sold_vehicle_publication_action": forms.Select(
                attrs={"class": "backoffice-select"}
            ),
        }
        labels = {
            "inbound_mode": "روش دریافت پیام",
            "staff_bot_enabled": "فعال‌بودن عملیات کارمندان در Bot",
            "customer_notifications_enabled": "ارسال اعلان تغییر مرحله برای مشتری",
            "vehicle_channel_sync_enabled": "فعال‌سازی همگام‌سازی خودرو با کانال",
            "default_vehicle_channel": "کانال پیش‌فرض خودروها",
            "sold_vehicle_publication_action": "رفتار پست پس از فروش خودرو",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_vehicle_channel"].queryset = TelegramChannel.objects.filter(
            is_active=True,
        ).order_by("name")
        # Keep the stable database values, but present every operational
        # choice in the Persian backoffice UI.
        self.fields["inbound_mode"].choices = (
            (TelegramIntegrationSettings.InboundMode.WEBHOOK, "وب‌هوک (برای سرور واقعی)"),
            (TelegramIntegrationSettings.InboundMode.POLLING, "دریافت دوره‌ای (برای توسعهٔ محلی)"),
        )
        self.fields["sold_vehicle_publication_action"].choices = (
            (
                TelegramIntegrationSettings.SoldPublicationAction.MARK_SOLD,
                "علامت‌گذاری پست به‌عنوان فروخته‌شده",
            ),
            (
                TelegramIntegrationSettings.SoldPublicationAction.DELETE,
                "حذف پست از کانال",
            ),
        )
        for name in (
            "staff_bot_enabled",
            "customer_notifications_enabled",
            "vehicle_channel_sync_enabled",
        ):
            self.fields[name].widget.attrs["class"] = "backoffice-checkbox"


class TelegramChannelForm(forms.ModelForm):
    class Meta:
        model = TelegramChannel
        fields = ["name", "chat_id", "username", "is_active", "publish_available_vehicles"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "backoffice-input"}),
            "chat_id": forms.NumberInput(attrs={"class": "backoffice-input", "dir": "ltr"}),
            "username": forms.TextInput(
                attrs={"class": "backoffice-input", "dir": "ltr", "placeholder": "@channel_name"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "backoffice-checkbox"}),
            "publish_available_vehicles": forms.CheckboxInput(
                attrs={"class": "backoffice-checkbox"}
            ),
        }
        labels = {
            "name": "نام مدیریتی کانال",
            "chat_id": "Channel ID",
            "username": "Username کانال",
            "is_active": "کانال فعال است",
            "publish_available_vehicles": "برای انتشار خودروهای موجود مجاز است",
        }
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
