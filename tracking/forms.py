from django import forms


class PublicTrackingLookupForm(forms.Form):
    tracking_code = forms.CharField(
        label="کد رهگیری",
        max_length=40,
        strip=True,
        error_messages={
            "required": "لطفاً کد رهگیری را وارد کنید.",
        },
        widget=forms.TextInput(
            attrs={
                "placeholder": "مثال: OAL-...",
                "autocomplete": "off",
                "dir": "ltr",
            }
        ),
    )
