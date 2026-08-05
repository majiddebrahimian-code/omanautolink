from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from blog.services import public_post_queryset
from cars.public import public_car_queryset

from .models import StaticPage


class StaticPublicSitemap(Sitemap):
    priority = 0.7
    changefreq = "weekly"

    def items(self):
        return ["core:home", "cars:vehicle_list", "blog:post_list"]

    def location(self, item):
        return reverse(item)


class StaticPageSitemap(Sitemap):
    priority = 0.6
    changefreq = "monthly"

    def items(self):
        return StaticPage.objects.filter(is_published=True)

    def lastmod(self, item):
        return item.updated_at


class VehicleSitemap(Sitemap):
    priority = 0.8
    changefreq = "weekly"

    def items(self):
        return public_car_queryset().order_by("-updated_at")

    def lastmod(self, item):
        return item.updated_at


class BlogPostSitemap(Sitemap):
    priority = 0.6
    changefreq = "monthly"

    def items(self):
        return public_post_queryset()

    def lastmod(self, item):
        return item.updated_at


public_sitemaps = {
    "static": StaticPublicSitemap,
    "pages": StaticPageSitemap,
    "vehicles": VehicleSitemap,
    "blog": BlogPostSitemap,
}
