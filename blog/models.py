from django.conf import settings
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse


class Category(models.Model):
    name = models.CharField("نام دسته‌بندی", max_length=120)
    slug = models.SlugField("نامک", max_length=140, unique=True, allow_unicode=True)

    class Meta:
        verbose_name = "دسته‌بندی وبلاگ"
        verbose_name_plural = "دسته‌بندی‌های وبلاگ"

    def __str__(self):
        return self.name


class BlogConfiguration(models.Model):
    """Editorial and SEO defaults for the public blog.

    The website reads this typed configuration directly.  It deliberately does
    not contain Telegram delivery settings: publishing content to a Telegram
    channel is a future integration concern and must go through a durable
    outbox, rather than being coupled to a web-admin save.
    """

    site_configuration = models.OneToOneField(
        "core.SiteConfiguration",
        on_delete=models.CASCADE,
        related_name="blog_configuration",
        verbose_name="تنظیمات اصلی سایت",
    )
    listing_eyebrow = models.CharField(
        "تیتر کوتاه Ùهرست وبلاگ",
        max_length=120,
        default="راهنما و تجربه",
    )
    listing_title = models.CharField(
        "عنوان Ùهرست وبلاگ",
        max_length=180,
        default="مجلهٔ واردات خودرو",
    )
    listing_description = models.TextField(
        "توضیح Ùهرست وبلاگ",
        default="محتوای کاربردی برای انتخاب خودرو و درک Ùرایند واردات و تحویل.",
    )
    default_meta_title = models.CharField(
        "عنوان پیش‌فرض سئوی وبلاگ",
        max_length=160,
        blank=True,
    )
    default_meta_description = models.CharField(
        "توضیح پیش‌فرض سئوی وبلاگ",
        max_length=320,
        blank=True,
    )
    default_meta_keywords = models.CharField(
        "کلیدواژه‌های پیش‌فرض وبلاگ",
        max_length=500,
        blank=True,
    )
    default_og_image = models.ImageField(
        "تصویر پیش‌فرض اشتراک‌گذاری وبلاگ",
        upload_to="blog/seo/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )
    articles_per_page = models.PositiveSmallIntegerField(
        "تعداد مطلب در هر ØµÙحه",
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(48)],
    )

    class Meta:
        verbose_name = "تنظیمات وبلاگ"
        verbose_name_plural = "تنظیمات وبلاگ"

    @classmethod
    def get_solo(cls):
        """Return the one BlogConfiguration record for the public site."""

        from core.models import SiteConfiguration

        site_configuration = SiteConfiguration.get_solo()
        configuration, _ = cls.objects.get_or_create(
            site_configuration=site_configuration,
        )
        return configuration

    def __str__(self):
        return "تنظیمات وبلاگ"


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        PUBLISHED = "published", "منتشرشده"

    title = models.CharField("عنوان", max_length=220)
    slug = models.SlugField("نامک", max_length=240, unique=True, allow_unicode=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="posts",
        verbose_name="نویسنده",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="posts",
        verbose_name="دسته‌بندی",
    )
    cover_image = models.ImageField(
        "تصویر کاور",
        upload_to="blog/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )
    cover_image_alt = models.CharField(
        "متن جایگزین تصویر کاور",
        max_length=180,
        blank=True,
    )
    excerpt = models.TextField("خلاصهٔ مطلب", blank=True)
    is_featured = models.BooleanField(
        "مقالهٔ ویژهٔ مجله",
        default=False,
        help_text="فقط یک مقالهٔ منتشرشده به‌عنوان مقالهٔ ویژهٔ صفحهٔ مجله نمایش داده می‌شود.",
    )
    content = models.TextField("متن مطلب")
    status = models.CharField(
        "وضعیت انتشار",
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    published_at = models.DateTimeField("زمان انتشار", blank=True, null=True, db_index=True)
    created_at = models.DateTimeField("زمان ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    seo_title = models.CharField("عنوان سئو", max_length=160, blank=True)
    meta_description = models.CharField("توضیح سئو", max_length=320, blank=True)
    meta_keywords = models.CharField("کلیدواژه‌های سئو", max_length=500, blank=True)
    og_image = models.ImageField(
        "تصویر اشتراک‌گذاری",
        upload_to="blog/seo/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )

    class Meta:
        verbose_name = "مطلب وبلاگ"
        verbose_name_plural = "مطالب وبلاگ"
        ordering = ["-published_at", "-created_at"]
        permissions = [
            ("publish_post", "Can publish and unpublish blog posts"),
        ]

    def __str__(self):
        return self.title

    @property
    def image_alt_text(self):
        return self.cover_image_alt or self.title

    @property
    def author_display_name(self):
        if not self.author:
            return ""

        return self.author.get_full_name() or self.author.get_username()

    def get_absolute_url(self):
        return reverse("blog:post_detail", kwargs={"slug": self.slug})
