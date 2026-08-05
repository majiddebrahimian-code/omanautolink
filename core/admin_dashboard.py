"""Read-only, permission-aware data for the customised admin dashboard.

This module intentionally contains no lifecycle changes. The dashboard is a
presentation read-model: its links lead to existing Django admin pages, whose
actions already call the shared domain services.
"""

from django.urls import reverse


def _can_view(user, permission):
    return bool(user.is_active and user.is_staff and user.has_perm(permission))


def _with_adminlte_metadata(cards):
    """Add presentational tokens without coupling domain queries to a UI kit."""

    colors = {
        "blue": "info",
        "cyan": "primary",
        "amber": "warning",
        "purple": "purple",
        "green": "success",
        "rose": "danger",
        "telegram": "info",
    }
    icons = {
        "car": "fa-car",
        "showroom": "fa-car",
        "hold": "fa-clock-o",
        "request": "fa-envelope-o",
        "tracking": "fa-map-marker",
        "blog": "fa-newspaper-o",
        "telegram": "fa-paper-plane",
    }

    for card in cards:
        card["adminlte_tone"] = colors.get(card["tone"], "info")
        card["adminlte_icon"] = icons.get(card["icon"], "fa-circle-o")

    return cards


def build_admin_dashboard_cards(user):
    """Return only dashboard cards the current user may safely view."""

    if not user.is_active or not user.is_staff:
        return []

    cards = []

    from cars.models import Car, VehicleHold
    from customers.models import CustomVehicleRequest
    from tracking.models import Stage

    if _can_view(user, "cars.view_car"):
        visible_cars = Car.objects.filter(is_deleted=False)
        cards.extend(
            [
                {
                    "label": "خودروهای فعال",
                    "value": visible_cars.count(),
                    "description": "موجودی قابل مدیریت",
                    "icon": "car",
                    "tone": "blue",
                    "url": reverse("admin:cars_car_changelist"),
                },
                {
                    "label": "خودروهای آمادهٔ فروش",
                    "value": visible_cars.filter(status=Car.Status.FOR_SALE).count(),
                    "description": "نمایش‌پذیر در سایت",
                    "icon": "showroom",
                    "tone": "cyan",
                    "url": reverse("admin:cars_car_changelist") + "?status=for_sale",
                },
            ]
        )

    if _can_view(user, "cars.view_vehiclehold"):
        cards.append(
            {
                "label": "رزروهای موقت فعال",
                "value": VehicleHold.objects.filter(is_active=True).count(),
                "description": "نیازمند پیگیری مشاور",
                "icon": "hold",
                "tone": "amber",
                "url": reverse("admin:cars_vehiclehold_changelist") + "?is_active__exact=1",
            }
        )

    if _can_view(user, "customers.view_customvehiclerequest"):
        cards.append(
            {
                "label": "درخواست‌های جدید مشتری",
                "value": CustomVehicleRequest.objects.filter(
                    status=CustomVehicleRequest.Status.NEW
                ).count(),
                "description": "درخواست خودرو یا مشاوره",
                "icon": "request",
                "tone": "purple",
                "url": reverse("admin:customers_customvehiclerequest_changelist")
                + "?status=new",
            }
        )

    if _can_view(user, "tracking.view_stage"):
        cards.append(
            {
                "label": "مراحل فعال رهگیری",
                "value": Stage.objects.filter(is_active=True).count(),
                "description": "فرآیند خطی ارسال",
                "icon": "tracking",
                "tone": "green",
                "url": reverse("admin:tracking_stage_changelist"),
            }
        )

    if _can_view(user, "blog.view_post"):
        from blog.models import Post

        cards.append(
            {
                "label": "مقاله‌های منتشرشده",
                "value": Post.objects.filter(status=Post.Status.PUBLISHED).count(),
                "description": "محتوای عمومی و سئو",
                "icon": "blog",
                "tone": "rose",
                "url": reverse("admin:blog_post_changelist") + "?status=published",
            }
        )

    if user.is_superuser:
        from integrations.models import TelegramOutboxMessage

        cards.append(
            {
                "label": "پیام‌های تلگرام نیازمند بررسی",
                "value": TelegramOutboxMessage.objects.filter(
                    status__in=[
                        TelegramOutboxMessage.Status.RETRY,
                        TelegramOutboxMessage.Status.FAILED,
                    ]
                ).count(),
                "description": "Outbox و تلاش مجدد",
                "icon": "telegram",
                "tone": "telegram",
                "url": reverse("admin:integrations_telegramoutboxmessage_changelist"),
            }
        )

    return _with_adminlte_metadata(cards)


def build_admin_control_shortcuts(user):
    """Return only the editable site-control areas available to ``user``.

    These are navigation shortcuts, not a second settings system.  Each link
    opens the existing ModelAdmin view, which continues to enforce its own
    permission checks and save validation.
    """

    if not user.is_active or not user.is_staff:
        return []

    shortcuts = []

    if _can_view(user, "core.manage_site_identity"):
        shortcuts.append(
            {
                "label": "هویت برند و سئوی سایت",
                "description": "نام، لوگو، رنگ، راه ارتباطی و تنظیمات SEO",
                "url": reverse("admin:core_siteconfiguration_changelist"),
                "icon": "identity",
            }
        )

    if _can_view(user, "core.manage_site_content"):
        shortcuts.extend(
            [
                {
                    "label": "صفحهٔ نخست",
                    "description": "Hero، خودروهای منتخب، مسیر و CTAها",
                    "url": reverse("admin:core_homepageconfiguration_changelist"),
                    "icon": "home",
                },
                {
                    "label": "تنظیمات وبلاگ",
                    "description": "عنوان فهرست، سئوی پیش‌فرض و تعداد مقالات",
                    "url": reverse("admin:blog_blogconfiguration_changelist"),
                    "icon": "blog-settings",
                },
            ]
        )

    if _can_view(user, "core.manage_site_navigation"):
        shortcuts.append(
            {
                "label": "منوی Header",
                "description": "عنوان، ترتیب و لینک‌های منوی عمومی",
                "url": reverse("admin:core_headernavigationitem_changelist"),
                "icon": "navigation",
            }
        )

    if _can_view(user, "core.manage_site_footer"):
        shortcuts.append(
            {
                "label": "Footer سایت",
                "description": "ستون‌ها، لینک‌ها و ترتیب نمایش",
                "url": reverse("admin:core_footersection_changelist"),
                "icon": "footer",
            }
        )

    if _can_view(user, "core.manage_site_social_links"):
        shortcuts.append(
            {
                "label": "شبکه‌های اجتماعی",
                "description": "Telegram، Instagram و سایر لینک‌های عمومی",
                "url": reverse("admin:core_sociallink_changelist"),
                "icon": "social",
            }
        )

    if _can_view(user, "core.manage_static_pages"):
        shortcuts.append(
            {
                "label": "صفحات عمومی",
                "description": "خدمات، دربارهٔ ما، تماس و متن‌های قابل تغییر",
                "url": reverse("admin:core_staticpage_changelist"),
                "icon": "pages",
            }
        )

    return shortcuts
