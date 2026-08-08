"""Write-side use cases for editable public-site configuration.

Views only validate HTTP input.  These services own authorization, transactions
and model validation so a future Telegram or API editor can use the same rules.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.authorization import require_permission

from .models import HomePageConfiguration, SeoConfiguration, SiteConfiguration


def _save_bound_form(*, form, actor, permission):
    require_permission(
        actor=actor,
        permission=permission,
        error_message="شما اجازهٔ تغییر این بخش از تنظیمات سایت را ندارید.",
    )
    instance = form.save(commit=False)
    instance.full_clean()
    instance.save()
    return instance


@transaction.atomic
def update_site_identity_and_seo(*, identity_form, seo_form, actor):
    """Update the singleton configuration and its SEO companion together."""

    require_permission(
        actor=actor,
        permission="core.manage_site_identity",
        error_message="شما اجازهٔ ویرایش هویت سایت را ندارید.",
    )
    require_permission(
        actor=actor,
        permission="core.manage_site_seo",
        error_message="شما اجازهٔ ویرایش SEO سایت را ندارید.",
    )
    configuration = identity_form.save(commit=False)
    configuration.full_clean()
    configuration.save()

    seo_configuration = seo_form.save(commit=False)
    seo_configuration.site_configuration = configuration
    seo_configuration.full_clean()
    seo_configuration.save()
    return configuration, seo_configuration


@transaction.atomic
def update_home_page_configuration(*, form, actor):
    return _save_bound_form(
        form=form,
        actor=actor,
        permission="core.manage_site_content",
    )


@transaction.atomic
def create_site_collection_item(*, form, actor, permission, home_page_owned=False):
    require_permission(
        actor=actor,
        permission=permission,
        error_message="شما اجازهٔ ایجاد این آیتم را ندارید.",
    )
    instance = form.save(commit=False)
    if home_page_owned:
        instance.home_page = HomePageConfiguration.objects.get_or_create(
            site_configuration=SiteConfiguration.get_solo(),
        )[0]
    instance.full_clean()
    instance.save()
    return instance


@transaction.atomic
def update_site_collection_item(*, form, actor, permission):
    return _save_bound_form(form=form, actor=actor, permission=permission)


@transaction.atomic
def delete_site_collection_item(*, instance, actor, permission):
    require_permission(
        actor=actor,
        permission=permission,
        error_message="شما اجازهٔ حذف این آیتم را ندارید.",
    )
    instance.delete()
