from django import forms

from .models import Post
from .services import POST_EDITABLE_FIELDS


class BlogPostForm(forms.ModelForm):
    """Editorial form used by the custom panel; publishing is a separate action."""

    class Meta:
        model = Post
        fields = POST_EDITABLE_FIELDS
        labels = {
            "title": "عنوان مقاله",
            "slug": "نامک (آدرس مقاله)",
            "category": "دسته‌بندی",
            "cover_image": "تصویر کاور",
            "cover_image_alt": "متن جایگزین تصویر کاور",
            "excerpt": "خلاصهٔ مقاله",
            "content": "متن مقاله",
            "seo_title": "عنوان SEO",
            "meta_description": "توضیح SEO",
            "meta_keywords": "کلمات کلیدی SEO",
            "og_image": "تصویر اشتراک‌گذاری",
        }
        help_texts = {
            "slug": "پس از انتشار، برای حفظ سئو و لینک‌های قبلی آن را تغییر ندهید.",
            "cover_image_alt": "توضیحی کوتاه و واقعی از تصویر برای دسترس‌پذیری و سئو.",
            "excerpt": "خلاصه‌ای که در کارت مقاله و نتایج جست‌وجو نشان داده می‌شود.",
            "seo_title": "اختیاری؛ در صورت خالی بودن از عنوان مقاله استفاده می‌شود.",
            "meta_description": "اختیاری؛ در صورت خالی بودن از خلاصه یا متن مقاله استفاده می‌شود.",
            "meta_keywords": "کلمات را با ویرگول جدا کنید.",
            "og_image": "اختیاری؛ تصویر ویژهٔ اشتراک‌گذاری در شبکه‌های اجتماعی.",
        }
        widgets = {
            "title": forms.TextInput(
                attrs={"placeholder": "مثلاً راهنمای انتخاب خودرو از عمان"}
            ),
            "slug": forms.TextInput(
                attrs={"dir": "ltr", "placeholder": "oman-car-buying-guide"}
            ),
            "excerpt": forms.Textarea(
                attrs={"rows": 4, "placeholder": "خلاصهٔ کوتاه و کاربردی مقاله را بنویسید."}
            ),
            "content": forms.Textarea(
                attrs={"rows": 16, "placeholder": "متن کامل مقاله را بنویسید."}
            ),
            "seo_title": forms.TextInput(
                attrs={"placeholder": "حداکثر ۱۶۰ کاراکتر"}
            ),
            "meta_description": forms.Textarea(
                attrs={"rows": 4, "placeholder": "حداکثر ۳۲۰ کاراکتر"}
            ),
            "meta_keywords": forms.TextInput(
                attrs={"placeholder": "خودرو، عمان، واردات خودرو"}
            ),
            "cover_image": forms.ClearableFileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
            "og_image": forms.ClearableFileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
        }
        error_messages = {
            "title": {"required": "عنوان مقاله را وارد کنید."},
            "slug": {
                "required": "نامک مقاله را وارد کنید.",
                "unique": "این نامک قبلاً برای مقالهٔ دیگری استفاده شده است.",
            },
            "content": {"required": "متن مقاله را وارد کنید."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            existing_class = field.widget.attrs.get("class", "")

            if isinstance(field.widget, forms.Textarea):
                css_class = "backoffice-textarea"
            elif isinstance(field.widget, forms.ClearableFileInput):
                css_class = "backoffice-file-input"
            else:
                css_class = "backoffice-input"

            field.widget.attrs["class"] = f"{existing_class} {css_class}".strip()
            field.widget.attrs.setdefault("id", f"id_{name}")

    def clean_cover_image(self):
        return self._validate_editorial_image("cover_image")

    def clean_og_image(self):
        return self._validate_editorial_image("og_image")

    def _validate_editorial_image(self, field_name):
        image = self.cleaned_data.get(field_name)
        if not image:
            return image

        if image.size > 8 * 1024 * 1024:
            raise forms.ValidationError(
                "حجم تصویر نباید بیشتر از ۸ مگابایت باشد."
            )

        return image
