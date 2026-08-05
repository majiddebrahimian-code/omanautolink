from .public_site import get_public_site_context


def public_site(request):
    """Expose configurable public-site content to shared public templates."""

    if request.path.startswith("/admin/"):
        return {}

    return get_public_site_context()
