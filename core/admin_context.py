"""Context isolated to the customised internal administration interface."""

from django.db.utils import OperationalError, ProgrammingError

from .admin_dashboard import build_admin_control_shortcuts, build_admin_dashboard_cards
from .models import SiteConfiguration


def admin_shell(request):
    """Expose editable branding and dashboard data only under Django Admin."""

    resolver_match = getattr(request, "resolver_match", None)
    if not resolver_match or resolver_match.namespace != "admin":
        return {}

    try:
        site_config = SiteConfiguration.get_solo()
    except (OperationalError, ProgrammingError):
        # Allows migration and first boot to run before the settings table
        # exists. Default Django strings remain a safe fallback.
        return {}

    context = {"admin_site_config": site_config}

    if (
        request.user.is_authenticated
        and resolver_match.view_name == "admin:index"
    ):
        context["admin_dashboard_cards"] = build_admin_dashboard_cards(
            request.user
        )
        context["admin_control_shortcuts"] = build_admin_control_shortcuts(
            request.user
        )

    return context
