from django.db import transaction
from django.db.models.signals import post_delete, post_save

from .models import (
    FooterLink,
    FooterSection,
    HeaderNavigationItem,
    HomeFeatureCard,
    HomePageConfiguration,
    HomeQuickAction,
    SeoConfiguration,
    SiteConfiguration,
    SocialLink,
)
from .public_site import clear_public_site_context_cache


PUBLIC_SITE_MODELS = (
    SiteConfiguration,
    SeoConfiguration,
    HeaderNavigationItem,
    FooterSection,
    FooterLink,
    SocialLink,
    HomePageConfiguration,
    HomeFeatureCard,
    HomeQuickAction,
)


def _clear_public_site_cache(**kwargs):
    # A site-content save can occur inside an atomic admin/service operation.
    # Deleting the cache before commit would let another request rebuild it with
    # old database values and leave the public site stale after commit.
    transaction.on_commit(clear_public_site_context_cache)


for public_site_model in PUBLIC_SITE_MODELS:
    post_save.connect(
        _clear_public_site_cache,
        sender=public_site_model,
        dispatch_uid=f"core.clear_public_site_cache.save.{public_site_model.__name__}",
    )
    post_delete.connect(
        _clear_public_site_cache,
        sender=public_site_model,
        dispatch_uid=f"core.clear_public_site_cache.delete.{public_site_model.__name__}",
    )
