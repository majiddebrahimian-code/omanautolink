import math

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone
from django.shortcuts import get_object_or_404, render
from django.utils.html import strip_tags
from django.utils.text import Truncator

from core.seo import breadcrumb_schema, image_absolute_url, page_context

from .models import BlogConfiguration, Category
from .services import public_post_queryset


def _post_description(post):
    """Return concise plain text that is safe to use in a metadata tag."""

    source = post.meta_description or post.excerpt or strip_tags(post.content)
    return Truncator(source.strip()).chars(300)


def _attach_reading_time(posts):
    """Attach a presentation-only reading-time value without storing derived data."""

    for post in posts:
        word_count = len(strip_tags(post.content).split())
        post.reading_time_minutes = max(1, math.ceil(word_count / 200))


def _blog_listing_schema(*, request, posts):
    """Describe the visible page of articles for search engines."""

    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": position,
                "url": request.build_absolute_uri(post.get_absolute_url()),
                "name": post.title,
            }
            for position, post in enumerate(posts, start=1)
        ],
    }


def _article_schema(*, request, post, description, site_config):
    post_url = post.get_absolute_url()
    published_at = post.published_at or post.created_at

    article_schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post.title,
        "description": description,
        "datePublished": published_at.isoformat(),
        "dateModified": post.updated_at.isoformat(),
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": request.build_absolute_uri(post_url),
        },
        "publisher": {
            "@type": "Organization",
            "name": site_config.legal_name or site_config.site_name,
        },
    }

    image = post.og_image or post.cover_image
    image_url = image_absolute_url(request, image)
    if image_url:
        article_schema["image"] = [image_url]

    logo_url = image_absolute_url(
        request,
        site_config.logo_light or site_config.logo_dark,
    )
    if logo_url:
        article_schema["publisher"]["logo"] = {
            "@type": "ImageObject",
            "url": logo_url,
        }

    if post.author:
        article_schema["author"] = {
            "@type": "Person",
            "name": post.author_display_name,
        }

    return article_schema


def public_post_list(request):
    blog_config = BlogConfiguration.get_solo()
    query = (request.GET.get("q") or "").strip()
    active_category_slug = (request.GET.get("category") or "").strip()

    posts = public_post_queryset()
    # Sidebar counts reflect only articles that a public visitor may read.
    visible_post_filter = Q(
        posts__status="published",
    ) & (Q(posts__published_at__isnull=True) | Q(posts__published_at__lte=timezone.now()))
    categories = (
        Category.objects.filter(posts__in=posts)
        .annotate(public_post_count=Count("posts", filter=visible_post_filter))
        .distinct()
        .order_by("name")
    )

    if query:
        posts = posts.filter(title__icontains=query)

    active_category = None
    if active_category_slug:
        active_category = categories.filter(slug=active_category_slug).first()
        posts = posts.filter(category__slug=active_category_slug)

    result_count = posts.count()
    paginator = Paginator(posts, blog_config.articles_per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
    visible_posts = list(page_obj.object_list)

    # The feature is a first-page presentation choice.  It remains part of the
    # paginator, therefore a later editorial choice never changes page URLs.
    featured_post = None
    if page_obj.number == 1:
        featured_post = posts.filter(is_featured=True).first()
        if featured_post is None and visible_posts:
            featured_post = visible_posts[0]
    reading_posts = list(visible_posts)
    if featured_post and featured_post not in reading_posts:
        reading_posts.append(featured_post)
    _attach_reading_time(reading_posts)

    is_filtered_view = bool(query or active_category_slug)
    page_number = request.GET.get("page")

    listing_title = blog_config.listing_title
    if query:
        listing_title = f"جست‌وجوی Â«{query}Â» در {blog_config.listing_title}"
    elif active_category:
        listing_title = f"{active_category.name} | {blog_config.listing_title}"

    # Sidebar content must respect the active public filter and paginator;
    # never leak an article from a different category or later page.
    recent_posts = [
        post
        for post in visible_posts
        if post.pk != getattr(featured_post, "pk", None)
    ][:3]
    _attach_reading_time(recent_posts)

    context = {
        **page_context(
            request,
            title=(
                listing_title
                if is_filtered_view
                else blog_config.default_meta_title or listing_title
            ),
            description=(
                blog_config.default_meta_description
                or blog_config.listing_description
            ),
            keywords=blog_config.default_meta_keywords,
            canonical_path="/blog/",
            og_image=blog_config.default_og_image,
            noindex=is_filtered_view or page_number not in (None, "", "1"),
            structured_data=[
                breadcrumb_schema(
                    request,
                    [
                        ("ØµÙحهٔ اصلی", "/"),
                        ("مجله", "/blog/"),
                    ],
                ),
                _blog_listing_schema(request=request, posts=visible_posts),
            ],
        ),
        "blog_config": blog_config,
        "page_obj": page_obj,
        "featured_post": featured_post,
        "posts": [post for post in visible_posts if post.pk != getattr(featured_post, "pk", None)],
        "categories": categories,
        "active_category": active_category,
        "active_category_slug": active_category_slug,
        "query": query,
        "result_count": result_count,
        "recent_posts": recent_posts,
    }
    return render(request, "blog/post_list.html", context)


def public_post_detail(request, slug):
    post = get_object_or_404(public_post_queryset(), slug=slug)
    blog_config = BlogConfiguration.get_solo()
    post_url = post.get_absolute_url()
    description = _post_description(post)
    _attach_reading_time([post])

    related_queryset = public_post_queryset().exclude(pk=post.pk)
    if post.category_id:
        related_posts = list(related_queryset.filter(category_id=post.category_id)[:3])
        if len(related_posts) < 3:
            related_posts.extend(
                related_queryset.exclude(
                    pk__in=[related_post.pk for related_post in related_posts]
                )[: 3 - len(related_posts)]
            )
    else:
        related_posts = list(related_queryset[:3])
    _attach_reading_time(related_posts)

    metadata = page_context(
        request,
        title=post.seo_title or post.title,
        description=description,
        keywords=post.meta_keywords or blog_config.default_meta_keywords,
        canonical_path=post_url,
        og_image=post.og_image or post.cover_image or blog_config.default_og_image,
        og_type="article",
            article_published_at=post.published_at or post.created_at,
            article_modified_at=post.updated_at,
            article_section=post.category.name if post.category else "مجله",
            article_author=post.author_display_name,
        structured_data=[
            _article_schema(
                request=request,
                post=post,
                description=description,
                site_config=blog_config.site_configuration,
            ),
            breadcrumb_schema(
                request,
                [
                    ("ØµÙحهٔ اصلی", "/"),
                    ("مجله", "/blog/"),
                    (post.title, post_url),
                ],
            ),
        ],
    )

    context = {
        **metadata,
        "blog_config": blog_config,
        "post": post,
        "related_posts": related_posts,
    }
    return render(request, "blog/post_detail.html", context)
