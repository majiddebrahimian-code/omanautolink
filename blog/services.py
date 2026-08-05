"""Shared business rules for blog publication.

Web admin, a future API, and a future Telegram adapter must call these
functions instead of each changing a post's publication fields independently.
This module intentionally performs no external Telegram call.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.authorization import require_active_internal_staff, require_permission

from .models import Post


# These are descriptive/editorial fields only.  Lifecycle fields such as
# ``author``, ``status`` and ``published_at`` deliberately never come from a
# web form or a Telegram adapter.  Their rules live in the services below.
POST_EDITABLE_FIELDS = (
    "title",
    "slug",
    "category",
    "cover_image",
    "cover_image_alt",
    "excerpt",
    "content",
    "seo_title",
    "meta_description",
    "meta_keywords",
    "og_image",
)


def _require_post_permission(*, actor, permission, error_message):
    """Apply the same internal-staff and permission policy to every adapter."""

    require_permission(
        actor=actor,
        permission=permission,
        error_message=error_message,
    )


def _editable_post_data(post_data):
    """Reject lifecycle-field injection before persisting editorial changes."""

    unexpected_fields = set(post_data) - set(POST_EDITABLE_FIELDS)
    if unexpected_fields:
        raise ValidationError(
            "فیلدهای غیرمجاز برای ویرایش مقاله ارسال شده‌اند."
        )

    return {
        field_name: post_data[field_name]
        for field_name in POST_EDITABLE_FIELDS
        if field_name in post_data
    }


@transaction.atomic
def create_post(*, actor, post_data):
    """Create a private draft while keeping author and lifecycle data trusted."""

    _require_post_permission(
        actor=actor,
        permission="blog.add_post",
        error_message="شما اجازهٔ ایجاد مقالهٔ وبلاگ را ندارید.",
    )

    post = Post(
        author=actor,
        status=Post.Status.DRAFT,
        published_at=None,
        **_editable_post_data(post_data),
    )
    post.full_clean()
    prepare_post_for_save(post=post, actor=actor)
    post.save()
    return post


@transaction.atomic
def update_post(*, post_id, actor, post_data):
    """Update content/SEO fields without permitting lifecycle-field changes."""

    _require_post_permission(
        actor=actor,
        permission="blog.change_post",
        error_message="شما اجازهٔ ویرایش مقالهٔ وبلاگ را ندارید.",
    )

    post = Post.objects.select_for_update().get(pk=post_id)
    for field_name, value in _editable_post_data(post_data).items():
        setattr(post, field_name, value)

    post.full_clean()
    prepare_post_for_save(post=post, actor=actor)
    post.save()
    return post


@transaction.atomic
def delete_post(*, post_id, actor):
    """Permanently remove a post only after a permission-protected confirmation."""

    _require_post_permission(
        actor=actor,
        permission="blog.delete_post",
        error_message="شما اجازهٔ حذف مقالهٔ وبلاگ را ندارید.",
    )

    post = Post.objects.select_for_update().get(pk=post_id)
    post.delete()


def public_post_queryset(*, now=None):
    """Return only posts that are safe to expose on the public website.

    Legacy published records without a timestamp remain visible for backwards
    compatibility.  A future-dated timestamp is never visible before its
    publication time.
    """

    now = now or timezone.now()
    return (
        Post.objects.filter(status=Post.Status.PUBLISHED)
        .filter(Q(published_at__isnull=True) | Q(published_at__lte=now))
        .select_related("author", "category")
        .order_by("-published_at", "-created_at")
    )


def _require_publication_permission(*, actor):
    """Require an active internal content editor for a visibility change."""

    require_active_internal_staff(actor=actor)

    if actor.is_superuser:
        return

    # ``change_post`` keeps the existing Employee role compatible.  The
    # explicit permission lets an administrator later grant publication-only
    # access to another internal actor, including a controlled integration.
    if actor.has_perm("blog.publish_post") or actor.has_perm("blog.change_post"):
        return

    raise ValidationError("شما اجازهٔ تغییر وضعیت انتشار مطالب وبلاگ را ندارید.")


def prepare_post_for_save(*, post, actor):
    """Normalize one Post before it is saved by an adapter.

    A draft remains private.  A published post receives a timestamp exactly
    once.  Moving an already-published post back to draft clears that timestamp
    so a later re-publication receives a new, truthful publication time.
    """

    previous_status = None
    if post.pk:
        previous_status = (
            Post.objects.filter(pk=post.pk)
            .values_list("status", flat=True)
            .first()
        )

    publication_state_changed = previous_status != post.status
    if post.status == Post.Status.PUBLISHED and (
        publication_state_changed or not post.published_at
    ):
        _require_publication_permission(actor=actor)
        post.published_at = timezone.now()
    elif post.status == Post.Status.DRAFT and previous_status == Post.Status.PUBLISHED:
        _require_publication_permission(actor=actor)
        post.published_at = None

    return post


@transaction.atomic
def publish_post(*, post_id, actor):
    """Publish a post through the one shared publication workflow."""

    _require_publication_permission(actor=actor)
    post = Post.objects.select_for_update().get(pk=post_id)
    was_published = post.status == Post.Status.PUBLISHED
    post.status = Post.Status.PUBLISHED
    if not was_published:
        post.published_at = None
    prepare_post_for_save(post=post, actor=actor)
    post.save(update_fields=["status", "published_at", "updated_at"])
    return post


@transaction.atomic
def unpublish_post(*, post_id, actor):
    """Return a published post to the private draft state."""

    _require_publication_permission(actor=actor)
    post = Post.objects.select_for_update().get(pk=post_id)
    post.status = Post.Status.DRAFT
    prepare_post_for_save(post=post, actor=actor)
    post.save(update_fields=["status", "published_at", "updated_at"])
    return post
