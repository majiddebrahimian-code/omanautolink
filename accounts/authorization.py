from django.core.exceptions import ValidationError

from accounts.models import StaffProfile


def require_active_internal_staff(*, actor):
    """
    Ensures the actor is an authenticated, active internal staff user.
    """

    if actor is None or not actor.is_authenticated:
        raise ValidationError("برای انجام این عملیات باید وارد سیستم شوید.")

    if not actor.is_active:
        raise ValidationError("حساب کاربری شما غیرفعال است.")

    if not actor.is_staff:
        raise ValidationError("این عملیات فقط برای کاربران داخلی سیستم مجاز است.")


def require_permission(*, actor, permission, error_message):
    """
    Requires one explicit Django permission.

    A superuser bypasses the permission check, but still must be an
    authenticated, active internal staff user.
    """

    require_active_internal_staff(actor=actor)

    if actor.is_superuser:
        return

    if not actor.has_perm(permission):
        raise ValidationError(error_message)


def require_stage_confirmation_permission(*, actor, stage):
    """
    Requires stage-confirmation permission plus assignment to the
    exact Stage for ordinary Clearance Employees.
    """

    require_permission(
        actor=actor,
        permission="tracking.confirm_tracking_stage",
        error_message="شما اجازهٔ تأیید مراحل رهگیری را ندارید.",
    )

    if actor.is_superuser:
        return

    is_assigned_to_stage = StaffProfile.objects.filter(
        user=actor,
        assigned_stages=stage,
    ).exists()

    if not is_assigned_to_stage:
        raise ValidationError("این کارمند به این مرحله تخصیص داده نشده است.")
