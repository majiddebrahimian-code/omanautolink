from functools import wraps

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied


def panel_permissions_required(*permissions):
    """
    Allow a staff member with at least one of the listed permissions.
    A System Administrator always has access.
    """

    if not permissions:
        raise ValueError("At least one permission is required.")

    def decorator(view):
        @staff_member_required
        @wraps(view)
        def wrapped_view(request, *args, **kwargs):
            has_access = request.user.is_superuser or any(
                request.user.has_perm(permission) for permission in permissions
            )

            if not has_access:
                raise PermissionDenied

            return view(request, *args, **kwargs)

        return wrapped_view

    return decorator


def system_administrator_required(view):
    """Allow only an active System Administrator."""

    @staff_member_required
    @wraps(view)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied

        return view(request, *args, **kwargs)

    return wrapped_view
