"""Small, typed helpers for public-page metadata and structured data."""

import json
from urllib.parse import urljoin

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.safestring import mark_safe

from .public_site import get_public_site_context


def public_base_url(request):
    configured_url = getattr(settings, "PUBLIC_SITE_URL", "").strip().rstrip("/")
    if configured_url:
        return configured_url

    return request.build_absolute_uri("/").rstrip("/")


def absolute_public_url(request, path):
    if path.startswith("http://") or path.startswith("https://"):
        return path

    return urljoin(f"{public_base_url(request)}/", path.lstrip("/"))


def image_absolute_url(request, image_field):
    if not image_field:
        return ""

    return absolute_public_url(request, image_field.url)


def serialize_json_ld(data):
    """Safely serialize typed schema data for a JSON-LD script element."""

    serialized = json.dumps(
        data,
        cls=DjangoJSONEncoder,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return mark_safe(serialized)


def organization_schema(request, site_context=None):
    site_context = site_context or get_public_site_context()
    site_config = site_context["site_config"]

    organization = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": site_config.legal_name or site_config.site_name,
        "url": public_base_url(request),
    }

    logo_url = image_absolute_url(request, site_config.logo_light or site_config.logo_dark)
    if logo_url:
        organization["logo"] = logo_url

    if site_config.support_phone:
        organization["telephone"] = site_config.support_phone
    if site_config.support_email:
        organization["email"] = site_config.support_email

    social_urls = [link.url for link in site_context["social_links"]]
    if social_urls:
        organization["sameAs"] = social_urls

    return organization


def breadcrumb_schema(request, items):
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": position,
                "name": name,
                "item": absolute_public_url(request, path),
            }
            for position, (name, path) in enumerate(items, start=1)
        ],
    }


def page_context(
    request,
    *,
    title="",
    description="",
    keywords="",
    canonical_path=None,
    og_image=None,
    og_type="website",
    article_published_at=None,
    article_modified_at=None,
    article_section="",
    article_author="",
    noindex=False,
    structured_data=None,
):
    """Return public template context for one page without accepting raw HTML."""

    site_context = get_public_site_context()
    site_config = site_context["site_config"]
    seo_config = site_context["seo_config"]

    if title:
        page_title = title
        if site_config.site_name and site_config.site_name not in page_title:
            page_title = f"{page_title} | {site_config.site_name}"
    else:
        page_title = seo_config.default_meta_title or site_config.site_name

    page_description = description or seo_config.default_meta_description
    page_keywords = keywords or seo_config.default_meta_keywords
    page_og_image = image_absolute_url(
        request,
        og_image or seo_config.default_og_image,
    )
    resolved_canonical_path = canonical_path or request.path

    return {
        **site_context,
        "page_title": page_title,
        "page_description": page_description,
        "page_keywords": page_keywords,
        "page_robots": "noindex, nofollow" if noindex else seo_config.default_robots,
        "canonical_url": absolute_public_url(request, resolved_canonical_path),
        "page_og_image": page_og_image,
        "page_og_type": og_type,
        "article_published_at": article_published_at,
        "article_modified_at": article_modified_at,
        "article_section": article_section,
        "article_author": article_author,
        "page_json_ld": serialize_json_ld(structured_data)
        if structured_data
        else "",
    }
