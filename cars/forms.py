from django import forms


class VehicleArchiveReasonForm(forms.Form):
    """Collects the mandatory human reason for an archive operation."""

    reason = forms.CharField(
        label="دلیل عملیات",
        max_length=1000,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "دلیل بایگانی یا بازگردانی خودرو را بنویسید.",
            }
        ),
        error_messages={
            "required": "ثبت دلیل برای این عملیات الزامی است.",
        },
    )
