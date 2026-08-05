"""Shared account and role services for internal staff.

The backoffice, Telegram administration, and future APIs must use this module
for staff writes.  It keeps Django's built-in User model, StaffProfile, role
groups, direct exceptional permissions, and audit history consistent.
"""

from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.authorization import require_active_internal_staff
from accounts.models import StaffManagementEvent, StaffProfile
from tracking.models import Stage


class RoleGroup:
    EMPLOYEE = "Employee"
    CLEARANCE_EMPLOYEE = "Clearance Employee"


class StaffBusinessRole:
    """Business-facing roles, deliberately separate from raw Django groups."""

    SYSTEM_ADMINISTRATOR = "system_administrator"
    EMPLOYEE = "employee"
    CLEARANCE_EMPLOYEE = "clearance_employee"
    UNASSIGNED = "unassigned"

    MANAGEABLE_CHOICES = (
        (EMPLOYEE, "کارمند"),
        (CLEARANCE_EMPLOYEE, "کارمند ترخیص"),
    )

    LABELS = {
        SYSTEM_ADMINISTRATOR: "مدیر اصلی سیستم",
        EMPLOYEE: "کارمند",
        CLEARANCE_EMPLOYEE: "کارمند ترخیص",
        UNASSIGNED: "بدون نقش عملیاتی",
    }


ROLE_PERMISSION_SPECS = {
    RoleGroup.EMPLOYEE: [
        # Vehicle inventory and media
        ("cars", "view_car"),
        ("cars", "add_car"),
        ("cars", "change_car"),
        ("cars", "view_carphoto"),
        ("cars", "add_carphoto"),
        ("cars", "change_carphoto"),
        ("cars", "delete_carphoto"),
        ("cars", "view_carspinframe"),
        ("cars", "add_carspinframe"),
        ("cars", "change_carspinframe"),
        ("cars", "delete_carspinframe"),
        ("cars", "view_vehiclehold"),
        ("cars", "publish_vehicle"),
        ("cars", "archive_vehicle"),
        # Blog and public-site content
        ("blog", "view_category"),
        ("blog", "add_category"),
        ("blog", "change_category"),
        ("blog", "delete_category"),
        ("blog", "view_post"),
        ("blog", "add_post"),
        ("blog", "change_post"),
        ("blog", "delete_post"),
        ("core", "view_sitesetting"),
        ("core", "change_sitesetting"),
        ("core", "manage_site_content"),
        ("core", "manage_site_navigation"),
        ("core", "manage_site_footer"),
        ("core", "manage_site_social_links"),
        ("core", "manage_static_pages"),
        # Customer requests and tracking visibility
        ("customers", "view_customer"),
        ("customers", "view_customvehiclerequest"),
        ("customers", "view_customvehiclerequestreadreceipt"),
        ("tracking", "view_stage"),
        ("tracking", "view_stagetransition"),
        ("tracking", "view_carstageprogress"),
        ("tracking", "view_trackingevent"),
    ],
    RoleGroup.CLEARANCE_EMPLOYEE: [
        # Minimum information required for stage operations
        ("cars", "view_car"),
        ("cars", "view_carphoto"),
        ("tracking", "view_stage"),
        ("tracking", "view_stagetransition"),
        ("tracking", "view_carstageprogress"),
        ("tracking", "view_trackingevent"),
        # Clearance-specific capabilities
        ("tracking", "confirm_tracking_stage"),
        ("tracking", "import_tracking_stage_updates"),
    ],
}


# Only business capabilities that are intentionally exceptional are selectable
# in the custom panel.  Raw Django permissions and arbitrary groups are never
# exposed to an administrator through this UI.
STAFF_EXCEPTION_PERMISSION_SPECS = {
    ("cars", "hold_vehicle"): {
        "label": "ثبت رزرو موقت ماشین",
        "description": "امکان رزرو داخلی یک ماشین آمادهٔ فروش برای مذاکره با مشتری.",
    },
    ("cars", "release_vehicle_hold"): {
        "label": "آزادکردن رزرو موقت",
        "description": "امکان برگرداندن ماشین رزروشده به موجودی قابل فروش.",
    },
    ("cars", "sell_vehicle"): {
        "label": "ثبت فروش ماشین",
        "description": "انتساب مشتری، فروش ماشین و ایجاد کد رهگیری را مجاز می‌کند.",
    },
    ("customers", "convert_custom_vehicle_request_to_sale"): {
        "label": "تبدیل درخواست اختصاصی به فروش",
        "description": "امکان اتصال درخواست خودروی اختصاصی به ماشین فروخته‌شده.",
    },
    ("tracking", "confirm_tracking_stage"): {
        "label": "تأیید مرحلهٔ تحویل",
        "description": "برای نقش کارمند، با تخصیص مرحله، امکان تأیید مرحله می‌دهد.",
    },
    ("tracking", "import_tracking_stage_updates"): {
        "label": "ثبت گروهی مرحله‌ها از Excel",
        "description": "امکان پردازش فایل Excel برای به‌روزرسانی‌های مرحله‌ای.",
    },
    ("tracking", "skip_tracking_stage"): {
        "label": "ردکردن مرحلهٔ تحویل",
        "description": "امکان عبور کنترل‌شده از یک مرحلهٔ تحویل.",
    },
    ("tracking", "correct_tracking_stage"): {
        "label": "اصلاح مرحلهٔ تحویل",
        "description": "امکان اصلاح وضعیت مرحله‌های ثبت‌شده با تاریخچهٔ کامل.",
    },
    ("tracking", "archive_tracking_stage"): {
        "label": "بایگانی مرحلهٔ تحویل",
        "description": "امکان تغییر ساختار مرحله‌های تحویل؛ فقط برای مسئولان بسیار مورداعتماد.",
    },
    ("integrations", "issue_customer_telegram_activation"): {
        "label": "صدور کد فعال‌سازی Telegram مشتری",
        "description": "امکان ساخت کد امن برای اتصال مشتری به اعلان‌های رهگیری Telegram.",
    },
}


def _get_permissions(permission_specs):
    permissions = []

    for app_label, codename in permission_specs:
        try:
            permission = Permission.objects.get(
                content_type__app_label=app_label,
                codename=codename,
            )
        except Permission.DoesNotExist as error:
            raise RuntimeError(
                f"Permission '{app_label}.{codename}' does not exist. "
                "Run migrations before synchronizing roles."
            ) from error

        permissions.append(permission)

    return permissions


@transaction.atomic
def ensure_default_role_groups():
    """Create or synchronize the baseline Employee and Clearance groups."""

    role_groups = {}

    for group_name, permission_specs in ROLE_PERMISSION_SPECS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.set(_get_permissions(permission_specs))
        role_groups[group_name] = group

    return role_groups


def get_staff_business_role(staff_user):
    """Return the only business role shown by the custom staff panel."""

    if staff_user.is_superuser:
        return StaffBusinessRole.SYSTEM_ADMINISTRATOR

    group_names = {group.name for group in staff_user.groups.all()}

    if RoleGroup.CLEARANCE_EMPLOYEE in group_names:
        return StaffBusinessRole.CLEARANCE_EMPLOYEE
    if RoleGroup.EMPLOYEE in group_names:
        return StaffBusinessRole.EMPLOYEE

    return StaffBusinessRole.UNASSIGNED


def get_staff_business_role_label(staff_user):
    return StaffBusinessRole.LABELS[get_staff_business_role(staff_user)]


def get_assignable_exception_permissions():
    """Return the curated direct-permission queryset for the staff form."""

    permission_ids = [
        permission.pk
        for permission in _get_permissions(STAFF_EXCEPTION_PERMISSION_SPECS)
    ]

    return Permission.objects.filter(pk__in=permission_ids).select_related(
        "content_type"
    ).order_by("content_type__app_label", "codename")


def get_exception_permission_details(permission):
    """Return presentation metadata for one intentionally selectable permission."""

    return STAFF_EXCEPTION_PERMISSION_SPECS.get(
        (permission.content_type.app_label, permission.codename),
        {},
    )


def _require_system_administrator(*, actor):
    require_active_internal_staff(actor=actor)

    if not actor.is_superuser:
        raise ValidationError("فقط مدیر اصلی سیستم اجازهٔ مدیریت کارکنان را دارد.")


def _clear_permission_cache(staff_user):
    for cache_key in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        staff_user.__dict__.pop(cache_key, None)


def _validate_manageable_staff(staff_user):
    if staff_user.is_superuser:
        raise ValidationError(
            "حساب مدیر اصلی از این بخش قابل ویرایش نیست؛ "
            "برای حفظ امنیت، نقش مدیر اصلی فقط از Django Admin مدیریت می‌شود."
        )

    if not staff_user.is_staff:
        raise ValidationError("فقط حساب‌های داخلی سیستم را می‌توان مدیریت کرد.")


def _validate_role(role):
    valid_roles = {
        StaffBusinessRole.EMPLOYEE,
        StaffBusinessRole.CLEARANCE_EMPLOYEE,
    }

    if role not in valid_roles:
        raise ValidationError("نقش انتخاب‌شده برای کارمند معتبر نیست.")


def _normalize_model_ids(values, *, field_label):
    if values is None:
        return []

    normalized_ids = []
    for value in values:
        raw_id = getattr(value, "pk", value)
        try:
            normalized_id = int(raw_id)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"مقدار «{field_label}» معتبر نیست.") from error

        if normalized_id <= 0:
            raise ValidationError(f"مقدار «{field_label}» معتبر نیست.")

        if normalized_id not in normalized_ids:
            normalized_ids.append(normalized_id)

    return normalized_ids


def _get_active_stages(stage_values):
    stage_ids = _normalize_model_ids(stage_values, field_label="مرحله")

    if not stage_ids:
        return []

    stages = list(
        Stage.objects.select_for_update()
        .filter(pk__in=stage_ids, is_active=True)
        .order_by("order", "pk")
    )

    if len(stages) != len(stage_ids):
        raise ValidationError(
            "فقط مرحله‌های فعال تحویل قابل تخصیص به کارمند هستند."
        )

    return stages


def _get_curated_exception_permissions(permission_values):
    permission_ids = _normalize_model_ids(
        permission_values,
        field_label="دسترسی ویژه",
    )

    if not permission_ids:
        return []

    allowed_permissions = list(get_assignable_exception_permissions())
    allowed_by_id = {permission.pk: permission for permission in allowed_permissions}

    if any(permission_id not in allowed_by_id for permission_id in permission_ids):
        raise ValidationError("یک یا چند دسترسی ویژهٔ انتخاب‌شده مجاز نیستند.")

    return [allowed_by_id[permission_id] for permission_id in permission_ids]


def _role_group_name(role):
    return {
        StaffBusinessRole.EMPLOYEE: RoleGroup.EMPLOYEE,
        StaffBusinessRole.CLEARANCE_EMPLOYEE: RoleGroup.CLEARANCE_EMPLOYEE,
    }[role]


def _permission_codes(permissions):
    return sorted(
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in permissions
    )


def _staff_snapshot(staff_user, profile=None):
    """Build a JSON-safe, secret-free audit snapshot."""

    if profile is None:
        profile = StaffProfile.objects.filter(user=staff_user).first()

    allowed_permission_ids = list(
        get_assignable_exception_permissions().values_list("pk", flat=True)
    )
    exceptional_permissions = list(
        staff_user.user_permissions.filter(pk__in=allowed_permission_ids).select_related(
            "content_type"
        )
    )

    return {
        "username": staff_user.username,
        "first_name": staff_user.first_name,
        "last_name": staff_user.last_name,
        "email": staff_user.email,
        "phone": profile.phone if profile else "",
        "is_active": staff_user.is_active,
        "role": get_staff_business_role(staff_user),
        "assigned_stage_ids": (
            list(profile.assigned_stages.order_by("order", "pk").values_list("pk", flat=True))
            if profile
            else []
        ),
        "exceptional_permissions": _permission_codes(exceptional_permissions),
    }


def _record_staff_management_event(*, staff_user, actor, action, changes, source):
    return StaffManagementEvent.objects.create(
        staff_user=staff_user,
        performed_by=actor,
        action=action,
        changes=changes,
        source=source,
    )


def _validate_identity_fields(*, username, email, exclude_user_id=None):
    user_model = get_user_model()
    normalized_username = str(username or "").strip()
    normalized_email = str(email or "").strip()

    if not normalized_username:
        raise ValidationError("نام کاربری کارمند الزامی است.")

    username_queryset = user_model.objects.filter(username__iexact=normalized_username)
    if exclude_user_id is not None:
        username_queryset = username_queryset.exclude(pk=exclude_user_id)

    if username_queryset.exists():
        raise ValidationError("این نام کاربری قبلاً استفاده شده است.")

    if normalized_email:
        email_queryset = user_model.objects.filter(email__iexact=normalized_email)
        if exclude_user_id is not None:
            email_queryset = email_queryset.exclude(pk=exclude_user_id)

        if email_queryset.exists():
            raise ValidationError("این ایمیل قبلاً برای یک حساب دیگر ثبت شده است.")

    return normalized_username, normalized_email


def _set_staff_role_permissions_and_stages(
    *,
    staff_user,
    role,
    assigned_stages,
    exceptional_permissions,
):
    """Apply controlled role/permission changes and preserve unrelated grants."""

    role_groups = ensure_default_role_groups()
    staff_user.groups.set([role_groups[_role_group_name(role)]])

    allowed_permissions = list(get_assignable_exception_permissions())
    previous_curated_permissions = list(
        staff_user.user_permissions.filter(
            pk__in=[permission.pk for permission in allowed_permissions]
        )
    )
    if previous_curated_permissions:
        staff_user.user_permissions.remove(*previous_curated_permissions)
    if exceptional_permissions:
        staff_user.user_permissions.add(*exceptional_permissions)

    _clear_permission_cache(staff_user)
    profile, _ = StaffProfile.objects.get_or_create(user=staff_user)

    has_stage_confirmation_permission = staff_user.has_perm(
        "tracking.confirm_tracking_stage"
    )

    # A stage relation is not a permission.  It is retained only for staff
    # who have the underlying confirmation capability through their role or a
    # deliberately selected exception.
    effective_assigned_stages = (
        list(assigned_stages) if has_stage_confirmation_permission and staff_user.is_active else []
    )
    profile.assigned_stages.set(effective_assigned_stages)

    _clear_permission_cache(staff_user)
    return profile, effective_assigned_stages


@transaction.atomic
def create_staff_member(
    *,
    actor,
    username,
    raw_password,
    first_name="",
    last_name="",
    email="",
    phone="",
    role=StaffBusinessRole.EMPLOYEE,
    assigned_stages=None,
    exceptional_permissions=None,
    source=StaffManagementEvent.Source.BACKOFFICE,
):
    """Create one active internal employee with a controlled business role."""

    _require_system_administrator(actor=actor)
    _validate_role(role)
    normalized_username, normalized_email = _validate_identity_fields(
        username=username,
        email=email,
    )
    stages = _get_active_stages(assigned_stages)
    permissions = _get_curated_exception_permissions(exceptional_permissions)

    user_model = get_user_model()
    candidate_user = user_model(
        username=normalized_username,
        first_name=str(first_name or "").strip(),
        last_name=str(last_name or "").strip(),
        email=normalized_email,
        is_staff=True,
        is_active=True,
    )
    password_validation.validate_password(raw_password, user=candidate_user)

    staff_user = user_model.objects.create_user(
        username=normalized_username,
        password=raw_password,
        first_name=candidate_user.first_name,
        last_name=candidate_user.last_name,
        email=normalized_email,
        is_staff=True,
        is_active=True,
    )
    profile, _ = StaffProfile.objects.get_or_create(
        user=staff_user,
        defaults={"phone": str(phone or "").strip()},
    )
    if profile.phone != str(phone or "").strip():
        profile.phone = str(phone or "").strip()
        profile.save(update_fields=["phone"])

    profile, _ = _set_staff_role_permissions_and_stages(
        staff_user=staff_user,
        role=role,
        assigned_stages=stages,
        exceptional_permissions=permissions,
    )
    _record_staff_management_event(
        staff_user=staff_user,
        actor=actor,
        action=StaffManagementEvent.Action.CREATED,
        changes={"after": _staff_snapshot(staff_user, profile)},
        source=source,
    )

    return staff_user


@transaction.atomic
def update_staff_member(
    *,
    staff_user,
    actor,
    username,
    first_name="",
    last_name="",
    email="",
    phone="",
    role=StaffBusinessRole.EMPLOYEE,
    assigned_stages=None,
    exceptional_permissions=None,
    source=StaffManagementEvent.Source.BACKOFFICE,
):
    """Update a staff account and its controlled operational capabilities."""

    _require_system_administrator(actor=actor)
    user_model = get_user_model()
    locked_staff_user = user_model.objects.select_for_update().get(pk=staff_user.pk)
    _validate_manageable_staff(locked_staff_user)
    _validate_role(role)
    normalized_username, normalized_email = _validate_identity_fields(
        username=username,
        email=email,
        exclude_user_id=locked_staff_user.pk,
    )
    stages = _get_active_stages(assigned_stages)
    permissions = _get_curated_exception_permissions(exceptional_permissions)
    profile, _ = StaffProfile.objects.select_for_update().get_or_create(
        user=locked_staff_user,
    )
    before = _staff_snapshot(locked_staff_user, profile)

    locked_staff_user.username = normalized_username
    locked_staff_user.first_name = str(first_name or "").strip()
    locked_staff_user.last_name = str(last_name or "").strip()
    locked_staff_user.email = normalized_email
    locked_staff_user.save(
        update_fields=["username", "first_name", "last_name", "email"]
    )

    normalized_phone = str(phone or "").strip()
    if profile.phone != normalized_phone:
        profile.phone = normalized_phone
        profile.save(update_fields=["phone"])

    profile, _ = _set_staff_role_permissions_and_stages(
        staff_user=locked_staff_user,
        role=role,
        assigned_stages=stages,
        exceptional_permissions=permissions,
    )
    after = _staff_snapshot(locked_staff_user, profile)

    if before != after:
        _record_staff_management_event(
            staff_user=locked_staff_user,
            actor=actor,
            action=StaffManagementEvent.Action.UPDATED,
            changes={"before": before, "after": after},
            source=source,
        )

    return locked_staff_user


@transaction.atomic
def set_staff_active_state(
    *,
    staff_user,
    actor,
    is_active,
    reason="",
    source=StaffManagementEvent.Source.BACKOFFICE,
):
    """Deactivate/reactivate safely; no historical actor or audit data is lost."""

    _require_system_administrator(actor=actor)
    user_model = get_user_model()
    locked_staff_user = user_model.objects.select_for_update().get(pk=staff_user.pk)
    _validate_manageable_staff(locked_staff_user)

    if locked_staff_user.pk == actor.pk:
        raise ValidationError("نمی‌توانید حساب مدیریتی فعلی خودتان را غیرفعال کنید.")

    requested_state = bool(is_active)
    if locked_staff_user.is_active == requested_state:
        return locked_staff_user

    profile, _ = StaffProfile.objects.select_for_update().get_or_create(
        user=locked_staff_user,
    )
    before = _staff_snapshot(locked_staff_user, profile)
    revocation_details = {
        "revoked_active_telegram_links": 0,
        "revoked_pending_telegram_codes": 0,
    }

    if not requested_state:
        # Operational stage assignments stop with the account.  Past tracking
        # events still refer to the employee through protected FK relations.
        profile.assigned_stages.clear()

        from integrations.models import TelegramStaffLink
        from integrations.services import (
            revoke_pending_telegram_staff_link_codes,
            revoke_telegram_staff_link,
        )

        active_links = list(
            TelegramStaffLink.objects.select_for_update().filter(
                user=locked_staff_user,
                is_active=True,
            )
        )
        for link in active_links:
            revoke_telegram_staff_link(
                staff_link=link,
                actor=actor,
                reason="غیرفعال‌سازی حساب کارمند",
            )

        revocation_details["revoked_active_telegram_links"] = len(active_links)
        revocation_details["revoked_pending_telegram_codes"] = (
            revoke_pending_telegram_staff_link_codes(
                staff_user=locked_staff_user,
                actor=actor,
            )
        )

    locked_staff_user.is_active = requested_state
    locked_staff_user.save(update_fields=["is_active"])
    _clear_permission_cache(locked_staff_user)
    after = _staff_snapshot(locked_staff_user, profile)
    action = (
        StaffManagementEvent.Action.REACTIVATED
        if requested_state
        else StaffManagementEvent.Action.DEACTIVATED
    )
    _record_staff_management_event(
        staff_user=locked_staff_user,
        actor=actor,
        action=action,
        changes={
            "before": before,
            "after": after,
            "reason": str(reason or "").strip(),
            **revocation_details,
        },
        source=source,
    )

    return locked_staff_user


@transaction.atomic
def reset_staff_password(
    *,
    staff_user,
    actor,
    raw_password,
    source=StaffManagementEvent.Source.BACKOFFICE,
):
    """Set a password using Django validators without persisting the secret."""

    _require_system_administrator(actor=actor)
    user_model = get_user_model()
    locked_staff_user = user_model.objects.select_for_update().get(pk=staff_user.pk)
    _validate_manageable_staff(locked_staff_user)
    password_validation.validate_password(raw_password, user=locked_staff_user)

    locked_staff_user.set_password(raw_password)
    locked_staff_user.save(update_fields=["password"])
    _clear_permission_cache(locked_staff_user)
    _record_staff_management_event(
        staff_user=locked_staff_user,
        actor=actor,
        action=StaffManagementEvent.Action.PASSWORD_RESET,
        changes={"password_reset": True},
        source=source,
    )

    return locked_staff_user


@transaction.atomic
def issue_staff_telegram_link_code(
    *,
    staff_user,
    actor,
    ttl_minutes=None,
    source=StaffManagementEvent.Source.BACKOFFICE,
):
    """Issue one one-time Telegram linking code and audit only safe metadata."""

    _require_system_administrator(actor=actor)
    user_model = get_user_model()
    locked_staff_user = user_model.objects.select_for_update().get(pk=staff_user.pk)
    _validate_manageable_staff(locked_staff_user)

    from integrations.models import TelegramStaffLink
    from integrations.services import create_telegram_staff_link_code

    if TelegramStaffLink.objects.filter(
        user=locked_staff_user,
        is_active=True,
    ).exists():
        raise ValidationError(
            "این کارمند هم‌اکنون به یک حساب Telegram متصل است؛ "
            "ابتدا اتصال فعلی را لغو کنید."
        )

    result = create_telegram_staff_link_code(
        staff_user=locked_staff_user,
        actor=actor,
        ttl_minutes=ttl_minutes,
    )
    _record_staff_management_event(
        staff_user=locked_staff_user,
        actor=actor,
        action=StaffManagementEvent.Action.TELEGRAM_LINK_ISSUED,
        changes={
            "token_id": result["token"].pk,
            "expires_at": result["expires_at"].isoformat(),
        },
        source=source,
    )

    return result


@transaction.atomic
def revoke_staff_telegram_link(
    *,
    staff_user,
    actor,
    reason="",
    source=StaffManagementEvent.Source.BACKOFFICE,
):
    """Revoke the current staff Telegram link through the integrations service."""

    _require_system_administrator(actor=actor)
    user_model = get_user_model()
    locked_staff_user = user_model.objects.select_for_update().get(pk=staff_user.pk)
    _validate_manageable_staff(locked_staff_user)

    from integrations.models import TelegramStaffLink
    from integrations.services import revoke_telegram_staff_link

    active_link = (
        TelegramStaffLink.objects.select_for_update()
        .filter(user=locked_staff_user, is_active=True)
        .order_by("-linked_at", "-pk")
        .first()
    )
    if active_link is None:
        raise ValidationError("برای این کارمند اتصال فعال Telegram وجود ندارد.")

    revoked_link = revoke_telegram_staff_link(
        staff_link=active_link,
        actor=actor,
        reason=reason,
    )
    _record_staff_management_event(
        staff_user=locked_staff_user,
        actor=actor,
        action=StaffManagementEvent.Action.TELEGRAM_LINK_REVOKED,
        changes={
            "telegram_link_id": revoked_link.pk,
            "reason": str(reason or "").strip(),
        },
        source=source,
    )

    return revoked_link
