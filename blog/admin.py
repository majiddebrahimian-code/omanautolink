from django.contrib import admin, messages

from .models import BlogConfiguration, Category, Post
from .services import prepare_post_for_save, publish_post, unpublish_post


def _can_manage_blog_settings(request):
    user = request.user
    return bool(
        user.is_active
        and user.is_staff
        and (
            user.is_superuser
            or user.has_perm("core.manage_site_content")
            or user.has_perm("blog.change_blogconfiguration")
        )
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(BlogConfiguration)
class BlogConfigurationAdmin(admin.ModelAdmin):
    list_display = ["site_configuration", "listing_title", "articles_per_page"]
    fieldsets = [
        (
            "نمای Ùهرست وبلاگ",
            {
                "fields": [
                    "site_configuration",
                    "listing_eyebrow",
                    "listing_title",
                    "listing_description",
                    "articles_per_page",
                ]
            },
        ),
        (
            "Ù¾ÛŒØ´â€ŒÙرض‌های سئو و اشتراک‌گذاری",
            {
                "fields": [
                    "default_meta_title",
                    "default_meta_description",
                    "default_meta_keywords",
                    "default_og_image",
                ]
            },
        ),
    ]

    def has_module_permission(self, request):
        return _can_manage_blog_settings(request)

    def has_view_permission(self, request, obj=None):
        return _can_manage_blog_settings(request)

    def has_change_permission(self, request, obj=None):
        return _can_manage_blog_settings(request)

    def has_add_permission(self, request):
        return _can_manage_blog_settings(request) and not BlogConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "category",
        "author",
        "status",
        "is_featured",
        "published_at",
        "updated_at",
    ]
    list_filter = ["status", "is_featured", "category"]
    search_fields = [
        "title",
        "excerpt",
        "content",
        "seo_title",
        "meta_description",
        "meta_keywords",
    ]
    list_select_related = ["author", "category"]
    date_hierarchy = "published_at"
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ["published_at", "created_at", "updated_at"]
    actions = ["publish_selected", "unpublish_selected"]
    fieldsets = [
        (
            "محتوای مطلب",
            {
                "fields": [
                    "title",
                    "slug",
                    "author",
                    "category",
                    "excerpt",
                    "is_featured",
                    "content",
                ]
            },
        ),
        (
            "تصاویر",
            {"fields": ["cover_image", "cover_image_alt", "og_image"]},
        ),
        (
            "سئو",
            {"fields": ["seo_title", "meta_description", "meta_keywords"]},
        ),
        (
            "انتشار",
            {"fields": ["status", "published_at", "created_at", "updated_at"]},
        ),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("author", "category")

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user

        # The ordinary edit screen is only an adapter.  Timestamp and
        # authorization rules remain in the shared service layer so that a
        # future API or Telegram adapter cannot accidentally duplicate them.
        prepare_post_for_save(post=obj, actor=request.user)
        super().save_model(request, obj, form, change)

    @admin.action(description="انتشار مطالب انتخاب‌شده")
    def publish_selected(self, request, queryset):
        published_count = 0
        for post in queryset:
            publish_post(post_id=post.pk, actor=request.user)
            published_count += 1

        self.message_user(
            request,
            f"{published_count} مطلب منتشر شد.",
            level=messages.SUCCESS,
        )

    @admin.action(description="بازگرداندن مطالب انتخاب‌شده به پیش‌نویس")
    def unpublish_selected(self, request, queryset):
        unpublished_count = 0
        for post in queryset:
            unpublish_post(post_id=post.pk, actor=request.user)
            unpublished_count += 1

        self.message_user(
            request,
            f"{unpublished_count} مطلب به پیش‌نویس بازگردانده شد.",
            level=messages.SUCCESS,
        )
