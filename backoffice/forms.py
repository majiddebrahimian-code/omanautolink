from django import forms


class AuditLogFilterForm(forms.Form):
    """Validate read-only audit filters before they reach reporting queries."""

    SOURCE_CHOICES = (
        ("", "همهٔ رویدادها"),
        ("tracking", "رهگیری و تحویل"),
        ("inventory", "موجودی ماشین"),
        ("archive", "بایگانی ماشین"),
        ("staff", "مدیریت کارکنان"),
    )

    q = forms.CharField(
        required=False,
        label="جست‌وجو",
        widget=forms.TextInput(
            attrs={
                "class": "backoffice-input",
                "placeholder": "نام ماشین، کد رهگیری، کاربر یا مرحله",
            }
        ),
    )
    source = forms.ChoiceField(
        required=False,
        choices=SOURCE_CHOICES,
        label="نوع رویداد",
        widget=forms.Select(attrs={"class": "backoffice-select"}),
    )
    date_from = forms.DateField(
        required=False,
        label="از تاریخ",
        widget=forms.DateInput(
            attrs={"class": "backoffice-input", "type": "date"}
        ),
    )
    date_to = forms.DateField(
        required=False,
        label="تا تاریخ",
        widget=forms.DateInput(
            attrs={"class": "backoffice-input", "type": "date"}
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("date_from")
            and cleaned_data.get("date_to")
            and cleaned_data["date_from"] > cleaned_data["date_to"]
        ):
            self.add_error("date_to", "تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد.")
        return cleaned_data
