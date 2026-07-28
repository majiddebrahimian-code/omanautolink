from django import forms
from cars.models import Car


class PublicCustomVehicleRequestForm(forms.Form):
    full_name = forms.CharField(
        label="نام و نام خانوادگی",
        max_length=200,
        error_messages={
            "required": "نام و نام خانوادگی الزامی است.",
        },
    )

    phone = forms.CharField(
        label="شماره تلفن",
        max_length=20,
        error_messages={
            "required": "شماره تلفن الزامی است.",
        },
        widget=forms.TextInput(
            attrs={
                "dir": "ltr",
                "autocomplete": "tel",
            }
        ),
    )

    telegram_id = forms.CharField(
        label="شناسهٔ تلگرام",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "dir": "ltr",
                "placeholder": "اختیاری",
            }
        ),
    )

    desired_vehicle_description = forms.CharField(
        label="توضیح خودروی موردنظر",
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": (
                    "مثلاً: یک شاسی‌بلند خانوادگی سفید، "
                    "کم‌کارکرد و دارای سقف پانوراما می‌خواهم."
                ),
            }
        ),
        error_messages={
            "required": "توضیح خودروی موردنظر الزامی است.",
        },
    )

    preferred_brand = forms.CharField(
        label="برند موردنظر",
        max_length=100,
        required=False,
    )

    preferred_model = forms.CharField(
        label="مدل موردنظر",
        max_length=100,
        required=False,
    )

    preferred_year_from = forms.IntegerField(
        label="سال ساخت از",
        required=False,
        min_value=1900,
        max_value=2100,
        widget=forms.NumberInput(
            attrs={
                "dir": "ltr",
            }
        ),
    )

    preferred_year_to = forms.IntegerField(
        label="سال ساخت تا",
        required=False,
        min_value=1900,
        max_value=2100,
        widget=forms.NumberInput(
            attrs={
                "dir": "ltr",
            }
        ),
    )

    budget_amount = forms.DecimalField(
        label="بودجهٔ تقریبی (تومان)",
        max_digits=15,
        decimal_places=0,
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                "dir": "ltr",
            }
        ),
        error_messages={
            "required": "بودجهٔ تقریبی الزامی است.",
            "min_value": "بودجه باید بزرگ‌تر از صفر باشد.",
        },
    )

    preferred_color = forms.CharField(
        label="رنگ موردنظر",
        max_length=50,
        required=False,
    )

    notes = forms.CharField(
        label="توضیحات تکمیلی",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        year_from = cleaned_data.get("preferred_year_from")
        year_to = cleaned_data.get("preferred_year_to")

        if year_from is not None and year_to is not None and year_from > year_to:
            self.add_error(
                "preferred_year_to",
                "سال پایان نمی‌تواند از سال شروع کمتر باشد.",
            )

        return cleaned_data


class AdminCustomVehicleRequestConversionForm(forms.Form):
    car = forms.ModelChoiceField(
        label="خودروی رزرو‌شده",
        queryset=Car.objects.none(),
        error_messages={
            "required": "انتخاب خودروی رزرو‌شده الزامی است.",
            "invalid_choice": "خودروی انتخاب‌شده معتبر نیست.",
        },
    )

    telegram_id = forms.CharField(
        label="شناسهٔ تلگرام مشتری",
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "dir": "ltr",
            }
        ),
        error_messages={
            "required": "شناسهٔ تلگرام مشتری الزامی است.",
        },
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["car"].queryset = Car.objects.filter(
            status=Car.Status.ON_HOLD,
            is_deleted=False,
        ).order_by(
            "brand",
            "model",
            "year",
            "id",
        )
