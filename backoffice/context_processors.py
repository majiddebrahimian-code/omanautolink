from .navigation import build_panel_navigation


def panel_navigation(request):
    resolver_match = getattr(request, "resolver_match", None)

    if not resolver_match or resolver_match.namespace != "backoffice":
        return {}

    return {
        "panel_navigation": build_panel_navigation(
            request.user,
            current_view_name=resolver_match.view_name,
        ),
    }
