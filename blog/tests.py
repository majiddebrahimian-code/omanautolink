from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.public_site import clear_public_site_context_cache

from .models import BlogConfiguration, Category, Post
from .services import public_post_queryset, publish_post, unpublish_post


class BlogPublicationServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.editor = user_model.objects.create_user(
            username="blog-editor",
            password="test-password",
            is_staff=True,
        )
        self.editor.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="blog",
                codename="change_post",
            )
        )
        self.unprivileged_staff = user_model.objects.create_user(
            username="unprivileged-blog-user",
            password="test-password",
            is_staff=True,
        )
        self.post = Post.objects.create(
            title="راهنمای خرید خودرو از عمان",
            slug="oman-car-guide",
            content="متن نمونهٔ راهنمای خرید خودرو.",
        )

    def test_publish_post_assigns_publication_time(self):
        published_post = publish_post(
            post_id=self.post.pk,
            actor=self.editor,
        )

        self.assertEqual(published_post.status, Post.Status.PUBLISHED)
        self.assertIsNotNone(published_post.published_at)
        self.assertIn(published_post, public_post_queryset())

    def test_unpublish_post_hides_post_and_clears_publication_time(self):
        publish_post(post_id=self.post.pk, actor=self.editor)

        draft_post = unpublish_post(
            post_id=self.post.pk,
            actor=self.editor,
        )

        self.assertEqual(draft_post.status, Post.Status.DRAFT)
        self.assertIsNone(draft_post.published_at)
        self.assertNotIn(draft_post, public_post_queryset())

    def test_unprivileged_staff_cannot_publish(self):
        with self.assertRaises(ValidationError):
            publish_post(
                post_id=self.post.pk,
                actor=self.unprivileged_staff,
            )


class PublicBlogViewsTests(TestCase):
    def setUp(self):
        clear_public_site_context_cache()
        self.category = Category.objects.create(
            name="راهنمای واردات",
            slug="import-guide",
        )
        self.blog_config = BlogConfiguration.get_solo()
        self.blog_config.listing_eyebrow = "دانش واردات"
        self.blog_config.listing_title = "مجلهٔ آزمایشی"
        self.blog_config.listing_description = "راهنمای مستقل برای خرید و واردات خودرو"
        self.blog_config.default_meta_title = "سئوی فهرست وبلاگ"
        self.blog_config.default_meta_description = "توضیح پیش‌فرض فهرست وبلاگ"
        self.blog_config.default_meta_keywords = "خودرو, عمان, واردات"
        self.blog_config.articles_per_page = 1
        self.blog_config.save()

        self.visible_post = Post.objects.create(
            title="خودروی منتشرشده",
            slug="visible-post",
            category=self.category,
            content="متن اصلی قابل‌نمایش",
            excerpt="خلاصهٔ قابل‌نمایش",
            status=Post.Status.PUBLISHED,
            published_at=timezone.now(),
            seo_title="عنوان اختصاصی سئو",
            meta_description="توضیح اختصاصی سئو",
            meta_keywords="کلیدواژهٔ اختصاصی",
        )
        self.future_post = Post.objects.create(
            title="خودروی آینده",
            slug="future-post",
            content="این مطلب هنوز نباید دیده شود.",
            status=Post.Status.PUBLISHED,
            published_at=timezone.now() + timedelta(days=1),
        )
        self.draft_post = Post.objects.create(
            title="خودروی پیش‌نویس",
            slug="draft-post",
            content="این مطلب پیش‌نویس است.",
            status=Post.Status.DRAFT,
        )

    def tearDown(self):
        clear_public_site_context_cache()

    def test_list_displays_configured_content_and_only_visible_posts(self):
        response = self.client.get(reverse("blog:post_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "دانش واردات")
        self.assertContains(response, "مجلهٔ آزمایشی")
        self.assertContains(response, self.visible_post.title)
        self.assertNotContains(response, self.future_post.title)
        self.assertNotContains(response, self.draft_post.title)
        self.assertContains(response, "سئوی فهرست وبلاگ")

    def test_future_and_draft_posts_are_not_publicly_addressable(self):
        future_response = self.client.get(self.future_post.get_absolute_url())
        draft_response = self.client.get(self.draft_post.get_absolute_url())

        self.assertEqual(future_response.status_code, 404)
        self.assertEqual(draft_response.status_code, 404)

    def test_unicode_persian_slug_is_publicly_routable(self):
        persian_slug_post = Post.objects.create(
            title="راهنمای فارسی خودرو",
            slug="راهنمای-خرید-خودرو",
            content="متن قابل نمایش برای نامک فارسی.",
            status=Post.Status.PUBLISHED,
            published_at=timezone.now(),
        )

        response = self.client.get(persian_slug_post.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, persian_slug_post.title)

    def test_detail_uses_per_post_seo_and_article_schema(self):
        response = self.client.get(self.visible_post.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "عنوان اختصاصی سئو")
        self.assertContains(response, "توضیح اختصاصی سئو")
        self.assertContains(response, "کلیدواژهٔ اختصاصی")
        self.assertContains(response, '"@type":"Article"')
        self.assertContains(response, '"dateModified"')
        self.assertContains(response, 'property="og:type" content="article"')
        self.assertContains(response, 'property="article:published_time"')
        self.assertContains(response, 'property="article:modified_time"')

    def test_sitemap_excludes_future_and_draft_posts(self):
        response = self.client.get(reverse("sitemap"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("blog:post_list"))
        self.assertContains(response, self.visible_post.get_absolute_url())
        self.assertNotContains(response, self.future_post.get_absolute_url())
        self.assertNotContains(response, self.draft_post.get_absolute_url())

    def test_pagination_uses_the_configured_page_size(self):
        older_post = Post.objects.create(
            title="مطلب قدیمی‌تر",
            slug="older-visible-post",
            content="متن مطلب قدیمی‌تر",
            status=Post.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(days=1),
        )

        first_page = self.client.get(reverse("blog:post_list"))
        second_page = self.client.get(reverse("blog:post_list"), {"page": 2})

        self.assertContains(first_page, self.visible_post.title)
        self.assertNotContains(first_page, older_post.title)
        self.assertContains(second_page, older_post.title)

    def test_public_search_and_category_filter_are_noindex_and_preserve_visibility(self):
        another_category = Category.objects.create(
            name="رهگیری و تحویل",
            slug="tracking-delivery",
        )
        unrelated_post = Post.objects.create(
            title="راهنمای تحویل خودرو",
            slug="delivery-guide",
            category=another_category,
            content="مقالهٔ مربوط به تحویل.",
            status=Post.Status.PUBLISHED,
            published_at=timezone.now(),
        )

        response = self.client.get(
            reverse("blog:post_list"),
            {"q": "خودروی", "category": self.category.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.visible_post.title)
        self.assertNotContains(response, unrelated_post.title)
        self.assertContains(response, 'name="robots" content="noindex, nofollow"')
        self.assertContains(response, '"@type":"ItemList"')

    def test_detail_exposes_article_section_and_related_articles(self):
        related_post = Post.objects.create(
            title="مقالهٔ مرتبط واردات",
            slug="related-import-post",
            category=self.category,
            content="متن مقالهٔ مرتبط.",
            status=Post.Status.PUBLISHED,
            published_at=timezone.now(),
        )

        response = self.client.get(self.visible_post.get_absolute_url())

        self.assertContains(
            response,
            'property="article:section" content="راهنمای واردات"',
        )
        self.assertContains(response, related_post.title)
        self.assertContains(response, "دقیقه")
