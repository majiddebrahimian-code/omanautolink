from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from cars.public import attach_cover_photos, public_car_queryset, with_public_photos
from cars.spin import get_public_spin_payload
from tracking.models import Stage

from .models import StaticPage
from .public_site import get_public_site_context
from .seo import (
    absolute_public_url,
    breadcrumb_schema,
    organization_schema,
    page_context,
)


def home(request):
    public_site_context = get_public_site_context()
    home_config = public_site_context["home_config"]

    hero_car = None
    if home_config.hero_featured_car_id:
        hero_car = with_public_photos(public_car_queryset()).filter(
            pk=home_config.hero_featured_car_id
        ).first()
        if hero_car:
            attach_cover_photos([hero_car])

    hero_spin = get_public_spin_payload(hero_car) if hero_car else None

    featured_vehicles = list(
        with_public_photos(
            public_car_queryset()
            .filter(is_featured=True)
            .order_by("-created_at")[:5]
        )
    )
    attach_cover_photos(featured_vehicles)

    active_stages = list(Stage.objects.filter(is_active=True).order_by("order")[:5])
    feature_cards = list(
        home_config.feature_cards.filter(is_enabled=True).order_by("sort_order", "pk")
    )
    quick_actions = list(
        home_config.quick_actions.filter(is_enabled=True).order_by("sort_order", "pk")
    )

    site_config = public_site_context["site_config"]
    seo_config = public_site_context["seo_config"]
    structured_data = [
        organization_schema(request, public_site_context),
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": site_config.site_name,
            "url": absolute_public_url(request, "/"),
        },
    ]

    context = {
        **page_context(
            request,
            title=seo_config.default_meta_title or home_config.hero_title,
            description=seo_config.default_meta_description
            or home_config.hero_description,
            canonical_path="/",
            og_image=home_config.hero_background_image,
            structured_data=structured_data,
        ),
        "hero_car": hero_car,
        "hero_spin": hero_spin,
        "featured_vehicles": featured_vehicles,
        "active_stages": active_stages,
        "feature_cards": feature_cards,
        "quick_actions": quick_actions,
    }
    return render(request, "core/home.html", context)


def static_page(request, slug):
    page = get_object_or_404(
        StaticPage,
        slug=slug,
        is_published=True,
    )
    page_url = page.get_absolute_url()
    context = {
        **page_context(
            request,
            title=page.meta_title or page.title,
            description=page.meta_description or page.intro,
            keywords=page.meta_keywords,
            canonical_path=page_url,
            structured_data=breadcrumb_schema(
                request,
                [
                    ("صفحهٔ اصلی", "/"),
                    (page.title, page_url),
                ],
            ),
        ),
        "static_page": page,
    }
    return render(request, "core/static_page.html", context)


def robots_txt(request):
    sitemap_url = absolute_public_url(request, reverse("sitemap"))
    response = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /admin/",
            "Disallow: /integrations/",
            f"Sitemap: {sitemap_url}",
            "",
        ]
    )
    return HttpResponse(response, content_type="text/plain; charset=utf-8")
