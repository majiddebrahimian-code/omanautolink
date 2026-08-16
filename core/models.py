from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models
from django.urls import reverse


hex_color_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="رنگ باید به‌صورت کد شش‌رقمی HEX، مانند #2563EB، وارد شود.",
)


def validate_public_destination(value):
    """Allow only safe relative paths, anchors, and HTTP(S) public URLs."""

    destination = (value or "").strip()

    if destination.startswith("/") and not destination.startswith("//"):
        return

    if destination.startswith("#"):
        return

    parsed = urlparse(destination)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return

    raise ValidationError(
        "نشانی باید با / یا # شروع شود، یا یک نشانی کامل HTTP(S) باشد."
    )


class SiteSetting(models.Model):
    """Legacy key/value settings kept for backwards compatibility only."""

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)

    def __str__(self):
        return self.key


class SiteConfiguration(models.Model):
    """The single typed source of truth for public-site identity and contact data."""

    singleton_key = models.PositiveSmallIntegerField(
        default=1,
        unique=True,
        editable=False,
    )

    site_name = models.CharField(max_length=120, default="برند شما")
    legal_name = models.CharField(max_length=180, blank=True)
    tagline = models.CharField(max_length=220, blank=True)

    logo_light = models.FileField(
        upload_to="site/identity/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp", "svg"])],
    )
    logo_dark = models.FileField(
        upload_to="site/identity/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp", "svg"])],
    )
    favicon = models.FileField(
        upload_to="site/identity/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "ico"])],
    )

    primary_color = models.CharField(
        max_length=7,
        default="#2563EB",
        validators=[hex_color_validator],
    )
    accent_color = models.CharField(
        max_length=7,
        default="#38BDF8",
        validators=[hex_color_validator],
    )
    surface_color = models.CharField(
        max_length=7,
        default="#17191D",
        validators=[hex_color_validator],
    )

    support_phone = models.CharField(max_length=40, blank=True)
    support_email = models.EmailField(blank=True)
    telegram_url = models.URLField(blank=True)
    address = models.TextField(blank=True)
    copyright_text = models.CharField(max_length=220, blank=True)

    class Meta:
        verbose_name = "تنظیمات اصلی سایت"
        verbose_name_plural = "تنظیمات اصلی سایت"
        permissions = [
            ("manage_site_identity", "Can manage site identity and brand assets"),
            ("manage_site_seo", "Can manage global site SEO"),
        ]

    def clean(self):
        if self.singleton_key != 1:
            raise ValidationError("تنظیمات اصلی سایت فقط یک رکورد دارد.")

    @classmethod
    def get_solo(cls):
        configuration, _ = cls.objects.get_or_create(singleton_key=1)
        return configuration

    def __str__(self):
        return self.site_name or "تنظیمات سایت"


class SeoConfiguration(models.Model):
    site_configuration = models.OneToOneField(
        SiteConfiguration,
        on_delete=models.CASCADE,
        related_name="seo",
    )
    default_meta_title = models.CharField(max_length=160, blank=True)
    default_meta_description = models.CharField(max_length=320, blank=True)
    default_meta_keywords = models.CharField(max_length=500, blank=True)
    default_robots = models.CharField(
        max_length=80,
        default="index, follow",
    )
    google_site_verification = models.CharField(max_length=255, blank=True)
    bing_site_verification = models.CharField(max_length=255, blank=True)
    twitter_handle = models.CharField(max_length=80, blank=True)
    default_og_image = models.ImageField(
        upload_to="site/seo/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )

    class Meta:
        verbose_name = "تنظیمات سئوی سایت"
        verbose_name_plural = "تنظیمات سئوی سایت"

    def __str__(self):
        return f"سئو: {self.site_configuration}"


class HeaderNavigationItem(models.Model):
    label = models.CharField(max_length=80)
    destination = models.CharField(
        max_length=500,
        validators=[validate_public_destination],
    )
    aria_label = models.CharField(max_length=160, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)
    open_in_new_tab = models.BooleanField(default=False)

    class Meta:
        verbose_name = "آیتم منوی هدر"
        verbose_name_plural = "آیتم‌های منوی هدر"
        ordering = ["sort_order", "pk"]
        permissions = [
            ("manage_site_navigation", "Can manage public site navigation"),
        ]

    def __str__(self):
        return self.label


class FooterSection(models.Model):
    title = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ستون فوتر"
        verbose_name_plural = "ستون‌های فوتر"
        ordering = ["sort_order", "pk"]
        permissions = [
            ("manage_site_footer", "Can manage public site footer"),
        ]

    def __str__(self):
        return self.title


class FooterLink(models.Model):
    section = models.ForeignKey(
        FooterSection,
        on_delete=models.CASCADE,
        related_name="links",
    )
    label = models.CharField(max_length=100)
    destination = models.CharField(
        max_length=500,
        validators=[validate_public_destination],
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)
    open_in_new_tab = models.BooleanField(default=False)

    class Meta:
        verbose_name = "لینک فوتر"
        verbose_name_plural = "لینک‌های فوتر"
        ordering = ["sort_order", "pk"]

    def __str__(self):
        return f"{self.section}: {self.label}"


class SocialLink(models.Model):
    class Platform(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        INSTAGRAM = "instagram", "Instagram"
        WHATSAPP = "whatsapp", "WhatsApp"
        YOUTUBE = "youtube", "YouTube"
        LINKEDIN = "linkedin", "LinkedIn"
        OTHER = "other", "Other"

    platform = models.CharField(max_length=30, choices=Platform.choices)
    label = models.CharField(max_length=80, blank=True)
    url = models.URLField()
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = "لینک شبکهٔ اجتماعی"
        verbose_name_plural = "لینک‌های شبکه‌های اجتماعی"
        ordering = ["sort_order", "pk"]
        permissions = [
            ("manage_site_social_links", "Can manage public social links"),
        ]

    def __str__(self):
        return self.label or self.get_platform_display()


class HomePageConfiguration(models.Model):
    site_configuration = models.OneToOneField(
        SiteConfiguration,
        on_delete=models.CASCADE,
        related_name="home_page",
    )
    hero_eyebrow = models.CharField(max_length=120, blank=True)
    hero_title = models.CharField(max_length=220, blank=True)
    hero_description = models.TextField(blank=True)
    hero_background_image = models.ImageField(
        upload_to="site/home/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )
    hero_mobile_background_image = models.ImageField(
        upload_to="site/home/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )
    hero_image_alt = models.CharField(max_length=180, blank=True)
    hero_featured_car = models.ForeignKey(
        "cars.Car",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="hero_features",
    )
    primary_cta_label = models.CharField(max_length=80, blank=True)
    primary_cta_destination = models.CharField(
        max_length=500,
        blank=True,
        validators=[validate_public_destination],
    )
    secondary_cta_label = models.CharField(max_length=80, blank=True)
    secondary_cta_destination = models.CharField(
        max_length=500,
        blank=True,
        validators=[validate_public_destination],
    )
    featured_vehicles_heading = models.CharField(max_length=140, blank=True)
    route_title = models.CharField(max_length=140, blank=True)
    route_origin_label = models.CharField(max_length=80, blank=True)
    route_destination_label = models.CharField(max_length=80, blank=True)
    route_transport_label = models.CharField(max_length=120, blank=True)
    route_duration_label = models.CharField(max_length=120, blank=True)
    route_panel_image = models.ImageField(
        upload_to="site/home/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )
    tracking_section_heading = models.CharField(max_length=140, blank=True)
    tracking_section_description = models.TextField(blank=True)

    class Meta:
        verbose_name = "محتوای صفحهٔ اول"
        verbose_name_plural = "محتوای صفحهٔ اول"
        permissions = [
            ("manage_site_content", "Can manage public homepage content"),
        ]

    def clean(self):
        if (
            self.hero_featured_car_id
            and (
                self.hero_featured_car.is_deleted
                or self.hero_featured_car.status != "for_sale"
            )
        ):
            raise ValidationError(
                {"hero_featured_car": "فقط خودروهای فعال و آمادهٔ فروش می‌توانند در صفحهٔ اول نمایش داده شوند."}
            )

    def __str__(self):
        return "محتوای صفحهٔ اول"


class HomeFeatureCard(models.Model):
    class Icon(models.TextChoices):
        CAR = "car", "خودرو"
        TRACK = "track", "رهگیری"
        MESSAGE = "message", "پیام"
        SHIELD = "shield", "اطمینان"

    home_page = models.ForeignKey(
        HomePageConfiguration,
        on_delete=models.CASCADE,
        related_name="feature_cards",
    )
    icon = models.CharField(max_length=20, choices=Icon.choices, default=Icon.CAR)
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    cta_label = models.CharField(max_length=80, blank=True)
    cta_destination = models.CharField(
        max_length=500,
        blank=True,
        validators=[validate_public_destination],
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = "کارت صفحهٔ اول"
        verbose_name_plural = "کارت‌های صفحهٔ اول"
        ordering = ["sort_order", "pk"]

    def __str__(self):
        return self.title


class HomeQuickAction(models.Model):
    """A constrained, editor-managed shortcut for the homepage control rail.

    ``action`` is deliberately a fixed enum.  Templates can safely map each
    value to a known icon and never need to render an administrator-provided
    CSS class, SVG fragment, or JavaScript handler.
    """

    class Action(models.TextChoices):
        INVENTORY = "inventory", "خودروهای موجود"
        ROUTE = "route", "مسیر واردات"
        TRACKING = "tracking", "رهگیری خودرو"
        REQUEST = "request", "درخواست خودرو"
        SUPPORT = "support", "ارتباط با مشاور"

    home_page = models.ForeignKey(
        HomePageConfiguration,
        on_delete=models.CASCADE,
        related_name="quick_actions",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    label = models.CharField(max_length=80)
    destination = models.CharField(
        max_length=500,
        validators=[validate_public_destination],
    )
    aria_label = models.CharField(max_length=160, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)
    open_in_new_tab = models.BooleanField(default=False)

    class Meta:
        verbose_name = "دسترسی سریع صفحهٔ اول"
        verbose_name_plural = "دسترسی‌های سریع صفحهٔ اول"
        ordering = ["sort_order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["home_page", "action"],
                name="core_unique_home_quick_action_type",
            )
        ]

    def __str__(self):
        return self.label


class StaticPage(models.Model):
    slug = models.SlugField(max_length=80, unique=True, allow_unicode=True)
    title = models.CharField(max_length=180)
    intro = models.TextField(blank=True)
    body = models.TextField(blank=True)
    meta_title = models.CharField(max_length=160, blank=True)
    meta_description = models.CharField(max_length=320, blank=True)
    meta_keywords = models.CharField(max_length=500, blank=True)
    is_published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "صفحهٔ عمومی"
        verbose_name_plural = "صفحات عمومی"
        ordering = ["title"]
        permissions = [
            ("manage_static_pages", "Can manage public static pages"),
        ]

    def get_absolute_url(self):
        return reverse("core:static_page", kwargs={"slug": self.slug})

    def __str__(self):
        return self.title


class FaqCategory(models.Model):
    name = models.CharField(max_length=120)
    emoji = models.CharField(max_length=10, blank=True, default="❓")

    class Meta:
        verbose_name_plural = "FAQ categories"

    def __str__(self):
        return self.name


class FaqItem(models.Model):
    category = models.ForeignKey(
        FaqCategory,
        on_delete=models.CASCADE,
        related_name="items",
    )
    question = models.TextField()
    answer = models.TextField()

    def __str__(self):
        return self.question[:60]


class ContactMessage(models.Model):
    class Status(models.TextChoices):
        NEW="new","جدید"
        READ="read","خوانده‌شده"
        CLOSED="closed","بسته‌شده"
    full_name=models.CharField("نام و نام خانوادگی",max_length=160)
    email=models.EmailField("ایمیل")
    phone=models.CharField("شمارهٔ تلفن",max_length=40)
    subject=models.CharField("موضوع",max_length=180,blank=True)
    message=models.TextField("متن پیام")
    status=models.CharField("وضعیت",max_length=12,choices=Status.choices,default=Status.NEW)
    created_at=models.DateTimeField("زمان ثبت",auto_now_add=True)
    updated_at=models.DateTimeField("آخرین تغییر",auto_now=True)
    class Meta:
        verbose_name="پیام تماس"
        verbose_name_plural="پیام‌های تماس"
        ordering=["-created_at","-pk"]
    def __str__(self):return f"{self.full_name}: {self.subject or 'پیام تماس'}"
