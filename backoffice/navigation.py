from django.urls import reverse

SITE_SETTINGS_PERMISSIONS = (
    "core.manage_site_identity",
    "core.manage_site_content",
    "core.manage_site_seo",
    "core.manage_site_navigation",
    "core.manage_site_footer",
    "core.manage_site_social_links",
    "core.manage_static_pages",
)


def _may_access(user, *permissions):
    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and (
            user.is_superuser
            or any(user.has_perm(permission) for permission in permissions)
        )
    )


def _link(*, label, icon, url_name):
    return {
        "label": label,
        "icon": icon,
        "url": reverse(url_name),
        "url_name": url_name,
    }


def build_panel_navigation(user):
    navigation = []

    machine_items = []

    if _may_access(user, "cars.view_car"):
        machine_items.append(
            _link(
                label="ماشین‌ها",
                icon="fa-car",
                url_name="backoffice:machine_list",
            )
        )

    if _may_access(user, "cars.view_vehiclehold"):
        machine_items.append(
            _link(
                label="رزروهای موقت",
                icon="fa-clock-o",
                url_name="backoffice:vehicle_hold_list",
            )
        )

    if _may_access(user, "cars.view_car"):
        machine_items.append(
            {
                "label": "ماشین‌های فروخته‌شده",
                "icon": "fa-check-circle-o",
                "children": [
                    _link(
                        label="در انتظار تحویل",
                        icon="fa-truck",
                        url_name="backoffice:pending_delivery_list",
                    ),
                    _link(
                        label="تحویل‌داده‌شده",
                        icon="fa-handshake-o",
                        url_name="backoffice:delivered_machine_list",
                    ),
                ],
            }
        )

    if machine_items:
        navigation.append(
            {
                "label": "مدیریت ماشین",
                "icon": "fa-car",
                "items": machine_items,
            }
        )

    customer_items = []
    if _may_access(user, "customers.view_customvehiclerequest"):
        customer_items.append(
            _link(
                label="درخواست‌های خودروی سفارشی",
                icon="fa-paper-plane-o",
                url_name="backoffice:custom_vehicle_request_list",
            )
        )
    if _may_access(user, "customers.view_customer"):
        customer_items.append(
            _link(
                label="مشتریان",
                icon="fa-address-book-o",
                url_name="backoffice:customer_list",
            )
        )
    if customer_items:
        navigation.append(
            {
                "label": "مشتریان و درخواست‌ها",
                "icon": "fa-users",
                "items": customer_items,
            }
        )

    if _may_access(user, "tracking.confirm_tracking_stage"):
        navigation.append(
            {
                "label": "عملیات ترخیص",
                "icon": "fa-check-square-o",
                "items": [
                    _link(
                        label="ثبت و تکمیل مرحله",
                        icon="fa-qrcode",
                        url_name="backoffice:clearance_operation",
                    ),
                ],
            }
        )

    if user.is_authenticated and user.is_active and user.is_superuser:
        navigation.append(
            {
                "label": "گزارش‌ها و حسابرسی",
                "icon": "fa-line-chart",
                "items": [
                    _link(
                        label="داشبورد مدیریتی",
                        icon="fa-dashboard",
                        url_name="backoffice:dashboard",
                    ),
                    _link(
                        label="گزارش رویدادها",
                        icon="fa-history",
                        url_name="backoffice:audit_log",
                    ),
                ],
            }
        )
        navigation.append(
            {
                "label": "مدیریت کارکنان",
                "icon": "fa-users",
                "items": [
                    _link(
                        label="کارکنان",
                        icon="fa-users",
                        url_name="backoffice:staff_list",
                    ),
                    _link(
                        label="افزودن کارمند",
                        icon="fa-user-plus",
                        url_name="backoffice:staff_create",
                    ),
                    _link(
                        label="نقش‌ها و دسترسی‌ها",
                        icon="fa-shield",
                        url_name="backoffice:staff_role_guide",
                    ),
                ],
            }
        )

    blog_items = []

    if _may_access(user, "blog.add_post"):
        blog_items.append(
            _link(
                label="افزودن مقاله",
                icon="fa-plus-circle",
                url_name="backoffice:blog_post_create",
            )
        )

    if _may_access(user, "blog.view_post"):
        blog_items.append(
            _link(
                label="لیست مقالات",
                icon="fa-list-alt",
                url_name="backoffice:blog_post_list",
            )
        )

    if blog_items:
        navigation.append(
            {
                "label": "وبلاگ",
                "icon": "fa-newspaper-o",
                "items": blog_items,
            }
        )

    settings_items = []

    if _may_access(user, *SITE_SETTINGS_PERMISSIONS):
        settings_items.append(
            _link(
                label="تنظیمات وب‌سایت",
                icon="fa-cog",
                url_name="backoffice:site_settings",
            )
        )

    if user.is_authenticated and user.is_active and user.is_superuser:
        settings_items.append(
            {
                "label": "مراحل تحویل ماشین",
                "icon": "fa-map-signs",
                "children": [
                    _link(
                        label="تعریف مرحله",
                        icon="fa-plus-circle",
                        url_name="backoffice:stage_create",
                    ),
                    _link(
                        label="لیست مراحل",
                        icon="fa-list-alt",
                        url_name="backoffice:stage_list",
                    ),
                    _link(
                        label="بررسی و ترمیم مسیر",
                        icon="fa-random",
                        url_name="backoffice:stage_transition_repair",
                    ),
                ],
            }
        )

    if settings_items:
        navigation.append(
            {
                "label": "تنظیمات",
                "icon": "fa-sliders",
                "items": settings_items,
            }
        )

    return navigation
