from django.contrib.auth.models import Group, Permission
from django.db import transaction


class RoleGroup:
    EMPLOYEE = "Employee"
    CLEARANCE_EMPLOYEE = "Clearance Employee"


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


def _get_permissions(permission_specs):
    permissions = []

    for app_label, codename in permission_specs:
        try:
            permission = Permission.objects.get(
                content_type__app_label=app_label,
                codename=codename,
            )
        except Permission.DoesNotExist:
            raise RuntimeError(
                f"Permission '{app_label}.{codename}' does not exist. "
                "Run migrations before synchronizing roles."
            )

        permissions.append(permission)

    return permissions


@transaction.atomic
def ensure_default_role_groups():
    """
    Creates or synchronizes the baseline business-role groups.

    System Administrator is represented by Django's is_superuser flag,
    so no separate Administrator group is created.

    Exceptional permissions, such as sell_vehicle, are assigned by the
    System Administrator to specific authorized employees when needed.
    """

    role_groups = {}

    for group_name, permission_specs in ROLE_PERMISSION_SPECS.items():
        group, _ = Group.objects.get_or_create(
            name=group_name,
        )

        group.permissions.set(_get_permissions(permission_specs))

        role_groups[group_name] = group

    return role_groups
