from decimal import Decimal

from django import forms

from .models import Car, CarPhoto
from .services import INVENTORY_EDITABLE_FIELDS


class CarInventoryForm(forms.ModelForm):
    """Edits only descriptive inventory data, never lifecycle data."""

    class Meta:
        model = Car
        fields = INVENTORY_EDITABLE_FIELDS
        labels = {
            "title": "عنوان ماشین",
            "brand": "برند",
            "model": "مدل",
            "year": "سال ساخت",
            "color": "رنگ",
            "mileage": "کارکرد (کیلومتر)",
            "price_amount": "قیمت (تومان)",
            "description": "توضیحات",
            "location": "محل خودرو",
            "is_featured": "نمایش در بخش ویژهٔ سایت",
            "seo_title": "عنوان SEO",
            "seo_description": "توضیحات SEO",
            "seo_keywords": "کلمات کلیدی SEO",
        }
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "مشخصات، امکانات و توضیحات ماشین را بنویسید.",
                }
            ),
            "seo_description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "خلاصه‌ای مناسب برای موتورهای جست‌وجو بنویسید.",
                }
            ),
            "year": forms.NumberInput(attrs={"min": 1900, "step": 1}),
            "mileage": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "price_amount": forms.NumberInput(attrs={"min": 0, "step": 1}),
        }
        error_messages = {
            "title": {"required": "عنوان ماشین را وارد کنید."},
            "brand": {"required": "برند ماشین را وارد کنید."},
            "model": {"required": "مدل ماشین را وارد کنید."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Price is optional in the first inventory draft.  A missing value is
        # stored as zero and the public UI can render it as "توافقی".
        self.fields["price_amount"].required = False

        for name, field in self.fields.items():
            existing_class = field.widget.attrs.get("class", "")

            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = (
                    f"{existing_class} backoffice-checkbox".strip()
                )
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = (
                    f"{existing_class} backoffice-textarea".strip()
                )
            else:
                field.widget.attrs["class"] = (
                    f"{existing_class} backoffice-input".strip()
                )

            field.widget.attrs.setdefault("id", f"id_{name}")

    def clean_price_amount(self):
        value = self.cleaned_data.get("price_amount")

        if value in (None, ""):
            return Decimal("0")

        if value < 0:
            raise forms.ValidationError("قیمت نمی‌تواند منفی باشد.")

        return value


class MultipleImageInput(forms.ClearableFileInput):
    """A Django widget that deliberately accepts more than one image file."""

    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """Validate every selected image through Django's normal ImageField rules."""

    def clean(self, data, initial=None):
        if not data:
            return []

        files = data if isinstance(data, (list, tuple)) else [data]
        single_image_clean = super().clean
        return [
            single_image_clean(uploaded_file, initial=None)
            for uploaded_file in files
        ]


class CarPhotoUploadForm(forms.Form):
    """Uploads a batch of normal gallery photos, not 360-degree frames."""

    images = MultipleImageField(
        label="انتخاب تصاویر",
        required=False,
        widget=MultipleImageInput(
            attrs={
                "class": "backoffice-file-input",
                "accept": "image/jpeg,image/png,image/webp",
                "multiple": True,
            }
        ),
    )

    def clean_images(self):
        images = self.cleaned_data["images"]

        if not images:
            raise forms.ValidationError("حداقل یک تصویر را انتخاب کنید.")

        return images


class CarPhotoMetadataForm(forms.ModelForm):
    """Edits only public gallery metadata for one existing image."""

    class Meta:
        model = CarPhoto
        fields = ["alt_text", "sort_order"]
        labels = {
            "alt_text": "متن جایگزین تصویر",
            "sort_order": "ترتیب نمایش",
        }
        widgets = {
            "alt_text": forms.TextInput(
                attrs={
                    "class": "backoffice-input",
                    "placeholder": "مثلاً نمای جلو ماشین",
                }
            ),
            "sort_order": forms.NumberInput(
                attrs={
                    "class": "backoffice-input",
                    "min": 0,
                    "step": 1,
                }
            ),
        }


class VehicleArchiveReasonForm(forms.Form):
    """Collects the mandatory human reason for an archive operation."""

    reason = forms.CharField(
        label="دلیل عملیات",
        max_length=1000,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "class": "backoffice-textarea",
                "placeholder": "دلیل بایگانی یا بازگردانی ماشین را بنویسید.",
            }
        ),
        error_messages={
            "required": "ثبت دلیل برای این عملیات الزامی است.",
        },
    )


class VehicleHoldCreateForm(forms.Form):
    """Collects the limited data needed for an internal temporary hold."""

    customer_name = forms.CharField(
        label="نام مشتری",
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "backoffice-input",
                "placeholder": "در صورت مشخص بودن وارد کنید.",
            }
        ),
    )
    customer_phone = forms.CharField(
        label="شماره تماس مشتری",
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "backoffice-input",
                "inputmode": "tel",
                "placeholder": "مثلاً ۰۹۱۲...",
            }
        ),
    )
    expires_at = forms.DateTimeField(
        label="زمان پایان رزرو",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "class": "backoffice-input",
                "type": "datetime-local",
            },
        ),
    )


class VehicleHoldReleaseForm(forms.Form):
    """Captures the optional operational note for a released hold."""

    release_note = forms.CharField(
        label="توضیح آزادسازی رزرو",
        max_length=1000,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "class": "backoffice-textarea",
                "placeholder": "مثلاً مذاکره با مشتری به نتیجه نرسید.",
            }
        ),
    )


class VehicleSaleForm(forms.Form):
    """The internal confirmation form that converts a hold into a sale."""

    full_name = forms.CharField(
        label="نام و نام خانوادگی خریدار",
        max_length=200,
        widget=forms.TextInput(attrs={"class": "backoffice-input"}),
    )
    phone = forms.CharField(
        label="شماره تماس خریدار",
        max_length=20,
        widget=forms.TextInput(
            attrs={"class": "backoffice-input", "inputmode": "tel"}
        ),
    )
    telegram_id = forms.CharField(
        label="شناسهٔ تلگرام خریدار",
        max_length=120,
        widget=forms.TextInput(
            attrs={
                "class": "backoffice-input",
                "placeholder": "مثلاً @username یا شناسهٔ عددی",
                "dir": "ltr",
            }
        ),
    )
