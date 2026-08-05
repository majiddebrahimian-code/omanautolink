from django.contrib import admin

from .models import (
    FaqCategory,
    FaqItem,
    FooterLink,
    FooterSection,
    HeaderNavigationItem,
    HomeFeatureCard,
    HomePageConfiguration,
    HomeQuickAction,
    SeoConfiguration,
    SiteConfiguration,
    SiteSetting,
    SocialLink,
    StaticPage,
)


def _can_manage(request, permission):
    return bool(
        request.user.is_active
        and (request.user.is_superuser or request.user.has_perm(permission))
    )


class FaqItemInline(admin.TabularInline):
    model = FaqItem
    extra = 1


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    """Legacy key/value settings; new public settings use typed models below."""

    list_display = ["key", "value"]


class SeoConfigurationInline(admin.StackedInline):
    model = SeoConfiguration
    extra = 0
    max_num = 1
    can_delete = False


class HomePageConfigurationInline(admin.StackedInline):
    model = HomePageConfiguration
    extra = 0
    max_num = 1
    can_delete = False


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    inlines = [SeoConfigurationInline, HomePageConfigurationInline]
    fieldsets = [
        ("هویت برند", {"fields": ["site_name", "legal_name", "tagline"]}),
        ("دارایی‌های تصویری", {"fields": ["logo_light", "logo_dark", "favicon"]}),
        (
            "رنگ‌ها",
            {"fields": ["primary_color", "accent_color", "surface_color"]},
        ),
        (
            "اطلاعات تماس",
            {
                "fields": [
                    "support_phone",
                    "support_email",
                    "telegram_url",
                    "address",
                    "copyright_text",
                ]
            },
        ),
    ]

    def has_module_permission(self, request):
        return _can_manage(request, "core.manage_site_identity")

    def has_view_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_identity")

    def has_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_identity")

    def has_add_permission(self, request):
        return _can_manage(request, "core.manage_site_identity") and not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HomePageConfiguration)
class HomePageConfigurationAdmin(admin.ModelAdmin):
    list_display = ["site_configuration", "hero_title", "hero_featured_car"]
    autocomplete_fields = ["hero_featured_car"]
    fieldsets = [
        ("معرفی اصلی", {"fields": ["hero_eyebrow", "hero_title", "hero_description"]}),
        (
            "تصویر و خودروی منتخب",
            {
                "fields": [
                    "hero_background_image",
                    "hero_mobile_background_image",
                    "hero_image_alt",
                    "hero_featured_car",
                ]
            },
        ),
        (
            "دکمه‌ها",
            {
                "fields": [
                    "primary_cta_label",
                    "primary_cta_destination",
                    "secondary_cta_label",
                    "secondary_cta_destination",
                ]
            },
        ),
        ("خودروهای موجود", {"fields": ["featured_vehicles_heading"]}),
        (
            "پنل مسیر واردات",
            {
                "fields": [
                    "route_title",
                    "route_origin_label",
                    "route_destination_label",
                    "route_transport_label",
                    "route_duration_label",
                    "route_panel_image",
                ]
            },
        ),
        (
            "بخش رهگیری",
            {"fields": ["tracking_section_heading", "tracking_section_description"]},
        ),
    ]

    def has_module_permission(self, request):
        return _can_manage(request, "core.manage_site_content")

    def has_view_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_content")

    def has_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_content")

    def has_add_permission(self, request):
        return _can_manage(request, "core.manage_site_content") and not HomePageConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HomeFeatureCard)
class HomeFeatureCardAdmin(admin.ModelAdmin):
    list_display = ["title", "icon", "sort_order", "is_enabled"]
    list_editable = ["sort_order", "is_enabled"]
    list_filter = ["icon", "is_enabled"]

    def has_module_permission(self, request):
        return _can_manage(request, "core.manage_site_content")

    def has_view_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_content")

    def has_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_content")

    def has_add_permission(self, request):
        return _can_manage(request, "core.manage_site_content")

    def has_delete_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_content")


@admin.register(HomeQuickAction)
class HomeQuickActionAdmin(admin.ModelAdmin):
    list_display = [
        "label",
        "action",
        "destination",
        "sort_order",
        "is_enabled",
        "open_in_new_tab",
    ]
    list_editable = ["sort_order", "is_enabled", "open_in_new_tab"]
    list_filter = ["action", "is_enabled", "open_in_new_tab"]
    search_fields = ["label", "destination", "aria_label"]
    list_select_related = ["home_page"]
    raw_id_fields = ["home_page"]

    def has_module_permission(self, request):
        return _can_manage(request, "core.manage_site_content")

    def has_view_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_content")

    def has_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_content")

    def has_add_permission(self, request):
        return _can_manage(request, "core.manage_site_content")

    def has_delete_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_content")


@admin.register(HeaderNavigationItem)
class HeaderNavigationItemAdmin(admin.ModelAdmin):
    list_display = ["label", "destination", "sort_order", "is_enabled", "open_in_new_tab"]
    list_editable = ["sort_order", "is_enabled", "open_in_new_tab"]
    search_fields = ["label", "destination"]

    def has_module_permission(self, request):
        return _can_manage(request, "core.manage_site_navigation")

    def has_view_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_navigation")

    def has_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_navigation")

    def has_add_permission(self, request):
        return _can_manage(request, "core.manage_site_navigation")

    def has_delete_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_navigation")


class FooterLinkInline(admin.TabularInline):
    model = FooterLink
    extra = 1

    def has_view_or_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_footer")

    def has_add_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_footer")

    def has_delete_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_footer")


@admin.register(FooterSection)
class FooterSectionAdmin(admin.ModelAdmin):
    list_display = ["title", "sort_order", "is_enabled"]
    list_editable = ["sort_order", "is_enabled"]
    inlines = [FooterLinkInline]

    def has_module_permission(self, request):
        return _can_manage(request, "core.manage_site_footer")

    def has_view_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_footer")

    def has_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_footer")

    def has_add_permission(self, request):
        return _can_manage(request, "core.manage_site_footer")

    def has_delete_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_footer")


@admin.register(SocialLink)
class SocialLinkAdmin(admin.ModelAdmin):
    list_display = ["platform", "label", "url", "sort_order", "is_enabled"]
    list_editable = ["sort_order", "is_enabled"]

    def has_module_permission(self, request):
        return _can_manage(request, "core.manage_site_social_links")

    def has_view_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_social_links")

    def has_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_social_links")

    def has_add_permission(self, request):
        return _can_manage(request, "core.manage_site_social_links")

    def has_delete_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_site_social_links")


@admin.register(StaticPage)
class StaticPageAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "is_published", "updated_at"]
    list_filter = ["is_published"]
    list_editable = ["is_published"]
    search_fields = ["title", "intro", "body"]
    prepopulated_fields = {"slug": ("title",)}

    def has_module_permission(self, request):
        return _can_manage(request, "core.manage_static_pages")

    def has_view_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_static_pages")

    def has_change_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_static_pages")

    def has_add_permission(self, request):
        return _can_manage(request, "core.manage_static_pages")

    def has_delete_permission(self, request, obj=None):
        return _can_manage(request, "core.manage_static_pages")


@admin.register(FaqCategory)
class FaqCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "emoji"]
    inlines = [FaqItemInline]
