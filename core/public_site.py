"""Read-model helpers for the configurable public website."""

from django.core.cache import cache
from django.db.models import Prefetch

from .models import (
    FooterLink,
    FooterSection,
    HeaderNavigationItem,
    HomePageConfiguration,
    SeoConfiguration,
    SiteConfiguration,
    SocialLink,
)


PUBLIC_SITE_CONTEXT_CACHE_KEY = "core:public-site-context:v1"
PUBLIC_SITE_CONTEXT_CACHE_TIMEOUT = 10 * 60


def clear_public_site_context_cache():
    cache.delete(PUBLIC_SITE_CONTEXT_CACHE_KEY)


def get_public_site_context():
    """Return the small, shared public-site configuration payload.

    Public templates use this helper through a context processor.  Caching is
    intentionally limited to site-owned content; vehicle inventory and tracking
    data remain request-specific and are never cached here.
    """

    cached_context = cache.get(PUBLIC_SITE_CONTEXT_CACHE_KEY)
    if cached_context is not None:
        return cached_context.copy()

    site_config = SiteConfiguration.get_solo()
    seo_config, _ = SeoConfiguration.objects.get_or_create(
        site_configuration=site_config,
    )
    home_config, _ = HomePageConfiguration.objects.get_or_create(
        site_configuration=site_config,
    )

    footer_sections = list(
        FooterSection.objects.filter(is_enabled=True)
        .prefetch_related(
            Prefetch(
                "links",
                queryset=FooterLink.objects.filter(is_enabled=True).order_by(
                    "sort_order",
                    "pk",
                ),
            )
        )
        .order_by("sort_order", "pk")
    )

    context = {
        "site_config": site_config,
        "seo_config": seo_config,
        "home_config": home_config,
        "header_navigation": list(
            HeaderNavigationItem.objects.filter(is_enabled=True).order_by(
                "sort_order",
                "pk",
            )
        ),
        "footer_sections": footer_sections,
        "social_links": list(
            SocialLink.objects.filter(is_enabled=True).order_by("sort_order", "pk")
        ),
    }

    cache.set(
        PUBLIC_SITE_CONTEXT_CACHE_KEY,
        context,
        PUBLIC_SITE_CONTEXT_CACHE_TIMEOUT,
    )
    return context.copy()
