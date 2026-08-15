from django import forms

from .models import BlogConfiguration, Category, Post
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
            "is_featured": 'نمایش به\u200cعنوان مقالهٔ ویژه',
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
            "seo_title": "اختیاری؛ در صورت خالی بودن از عنوان مقاله Ø§Ø³ØªÙاده می‌شود.",
            "meta_description": "اختیاری؛ در صورت خالی بودن از خلاصه یا متن مقاله Ø§Ø³ØªÙاده می‌شود.",
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
                "unique": "این نامک قبلاً برای مقالهٔ دیگری Ø§Ø³ØªÙاده شده است.",
            },
            "content": {"required": "متن مقاله را وارد کنید."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            existing_class = field.widget.attrs.get("class", "")

            if isinstance(field, forms.BooleanField):
                css_class = "backoffice-checkbox"
            elif isinstance(field.widget, forms.Textarea):
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


class BlogConfigurationForm(forms.ModelForm):
    """Typed settings for the public magazine landing page."""

    class Meta:
        model = BlogConfiguration
        fields = (
            "listing_eyebrow",
            "listing_title",
            "listing_description",
            "articles_per_page",
            "default_meta_title",
            "default_meta_description",
            "default_meta_keywords",
            "default_og_image",
        )
        labels = {
            "listing_eyebrow": "عنوان کوتاه بالای مجله",
            "listing_title": "عنوان اصلی صفحهٔ مجله",
            "listing_description": "توضیح معرفی مجله",
            "articles_per_page": "تعداد مقاله در هر صفحه",
            "default_meta_title": "عنوان پیش‌فرض SEO",
            "default_meta_description": "توضیح پیش‌فرض SEO",
            "default_meta_keywords": "کلیدواژه‌های پیش‌فرض SEO",
            "default_og_image": "تصویر پیش‌فرض اشتراک‌گذاری",
        }
        widgets = {
            "listing_description": forms.Textarea(attrs={"rows": 4}),
            "default_meta_description": forms.Textarea(attrs={"rows": 4}),
            "default_og_image": forms.ClearableFileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Textarea):
                css_class = "backoffice-textarea"
            elif isinstance(field.widget, forms.ClearableFileInput):
                css_class = "backoffice-file-input"
            else:
                css_class = "backoffice-input"
            field.widget.attrs["class"] = css_class
            field.widget.attrs.setdefault("id", f"id_{name}")


class BlogCategoryForm(forms.ModelForm):
    """Category form used only by the custom Backoffice interface."""

    class Meta:
        model = Category
        fields = ("name", "slug")
        labels = {"name": "نام دسته‌بندی", "slug": "نامک (آدرس)"}
        help_texts = {
            "slug": "از نامک پایدار استفاده کنید؛ تغییر آن پس از انتشار می‌تواند روی URLهای قبلی اثر بگذارد."
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "مثلاً راهنمای خرید"}),
            "slug": forms.TextInput(
                attrs={"dir": "ltr", "placeholder": "buying-guide"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "backoffice-input"

