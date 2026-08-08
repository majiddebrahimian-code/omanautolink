from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cars.models import Car

from .models import (
    HeaderNavigationItem,
    HomeQuickAction,
    SeoConfiguration,
    SiteConfiguration,
)
from .public_site import clear_public_site_context_cache


class PublicWebsiteTests(TestCase):
    def setUp(self):
        clear_public_site_context_cache()
        self.site_config = SiteConfiguration.get_solo()
        self.site_config.site_name = "برند آزمایشی"
        self.site_config.telegram_url = "https://t.me/example_consultant"
        self.site_config.save()

        self.seo_config, _ = SeoConfiguration.objects.get_or_create(
            site_configuration=self.site_config,
        )
        self.seo_config.default_meta_title = "عنوان سئوی قابل‌تنظیم"
        self.seo_config.default_meta_description = "توضیح سئوی قابل‌تنظیم"
        self.seo_config.default_meta_keywords = "واردات خودرو, رهگیری خودرو"
        self.seo_config.save()

        self.public_car = Car.objects.create(
            title="Featured Test Car",
            brand="Test Brand",
            model="Test Model",
            status=Car.Status.FOR_SALE,
            is_featured=True,
            price_amount=100,
        )
        self.hidden_car = Car.objects.create(
            title="Draft Test Car",
            brand="Test Brand",
            model="Draft Model",
            status=Car.Status.DRAFT,
            price_amount=100,
        )

    def test_homepage_uses_dynamic_identity_metadata_and_visible_inventory(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(response, "برند آزمایشی")
        self.assertContains(response, "عنوان سئوی قابل‌تنظیم")
        self.assertContains(response, "توضیح سئوی قابل‌تنظیم")
        self.assertContains(response, self.public_car.title)
        self.assertNotContains(response, self.hidden_car.title)
        self.assertContains(response, "مسیر واردات")
        self.assertContains(response, "مشاوره در تلگرام")

    def test_navigation_changes_are_rendered_from_database(self):
        HeaderNavigationItem.objects.create(
            label="راهنمای خرید",
            destination="/services/",
            sort_order=999,
        )

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "راهنمای خرید")

    def test_homepage_control_rail_uses_database_quick_actions(self):
        home_page = self.site_config.home_page
        quick_action, _ = HomeQuickAction.objects.get_or_create(
            home_page=home_page,
            action=HomeQuickAction.Action.SUPPORT,
            defaults={
                "label": "گفت‌وگو با مشاور",
                "destination": "/contact/",
                "sort_order": 90,
            },
        )
        quick_action.label = "گفت‌وگو با مشاور"
        quick_action.destination = "/contact/"
        quick_action.is_enabled = True
        quick_action.save()

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "lobby-layout")
        self.assertContains(response, "lobby-rail__action")
        self.assertContains(response, "گفت‌وگو با مشاور")
        self.assertContains(response, "lobby-icon--support")

    def test_public_vehicle_list_and_detail_exclude_non_public_vehicles(self):
        list_response = self.client.get(reverse("cars:vehicle_list"))
        detail_response = self.client.get(self.public_car.get_absolute_url())
        hidden_detail_response = self.client.get(self.hidden_car.get_absolute_url())

        self.assertContains(list_response, self.public_car.title)
        self.assertNotContains(list_response, self.hidden_car.title)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(hidden_detail_response.status_code, 404)

    def test_robots_and_sitemap_expose_only_public_indexable_pages(self):
        robots_response = self.client.get(reverse("robots_txt"))
        sitemap_response = self.client.get(reverse("sitemap"))

        self.assertContains(robots_response, "Sitemap: http://testserver/sitemap.xml")
        self.assertContains(robots_response, "Disallow: /admin/")
        self.assertEqual(sitemap_response.status_code, 200)
        self.assertContains(sitemap_response, self.public_car.get_absolute_url())
        self.assertNotContains(sitemap_response, self.hidden_car.get_absolute_url())

    def tearDown(self):
        clear_public_site_context_cache()


class AdminShellTests(TestCase):
    """Regression tests for the locally vendored PersianAdminLTE shell."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin-shell-user",
            email="admin-shell@example.com",
            password="secure-test-password",
        )

    def test_admin_login_uses_the_custom_rtl_shell(self):
        response = self.client.get(reverse("admin:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, "login-box")
        self.assertContains(response, "vendor/persian-adminlte/css/adminlte.min.css")

    def _legacy_admin_dashboard_snapshot(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "main-sidebar")
        self.assertContains(response, "small-box")
        self.assertContains(response, "تنظیمات قابل‌کنترل سایت")
