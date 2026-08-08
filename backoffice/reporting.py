"""Read-only management reporting built on the project's durable events.

This module deliberately does not create a second audit table.  Vehicle,
tracking, archive and staff services already create immutable records; this
module normalizes them only for reporting and never changes business data.
"""

from django.db.models import Case, CharField, Count, F, Q, Value, When
from django.db.models.functions import Cast, Coalesce

from accounts.models import StaffManagementEvent
from cars.models import Car, VehicleArchiveEvent, VehicleInventoryEvent
from customers.models import CustomVehicleRequest
from tracking.models import Stage, TrackingEvent


AUDIT_LABELS = {
    "tracking": {
        TrackingEvent.EventType.TRACKING_STARTED: "شروع رهگیری ماشین",
        TrackingEvent.EventType.STAGE_CONFIRMED: "ورود ماشین به مرحله",
        TrackingEvent.EventType.STAGE_COMPLETED: "تکمیل مرحلهٔ تحویل",
        TrackingEvent.EventType.STAGE_CORRECTED: "اصلاح مرحلهٔ تحویل",
        TrackingEvent.EventType.STAGE_SKIPPED: "ردکردن مرحلهٔ تحویل",
        TrackingEvent.EventType.STAGE_ARCHIVED: "تغییر ناشی از بایگانی مرحله",
    },
    "inventory": {
        VehicleInventoryEvent.Action.CREATED: "ثبت ماشین در موجودی",
        VehicleInventoryEvent.Action.UPDATED: "ویرایش موجودی یا تصاویر ماشین",
    },
    "archive": {
        VehicleArchiveEvent.Action.ARCHIVED: "بایگانی نرم ماشین",
        VehicleArchiveEvent.Action.RESTORED: "بازگردانی ماشین بایگانی‌شده",
    },
    "staff": {
        StaffManagementEvent.Action.CREATED: "ایجاد حساب کارمند",
        StaffManagementEvent.Action.UPDATED: "ویرایش نقش یا دسترسی کارمند",
        StaffManagementEvent.Action.PASSWORD_RESET: "بازنشانی رمز عبور کارمند",
        StaffManagementEvent.Action.DEACTIVATED: "غیرفعال‌سازی حساب کارمند",
        StaffManagementEvent.Action.REACTIVATED: "فعال‌سازی دوبارهٔ حساب کارمند",
        StaffManagementEvent.Action.TELEGRAM_LINK_ISSUED: "صدور کد اتصال Telegram",
        StaffManagementEvent.Action.TELEGRAM_LINK_REVOKED: "لغو اتصال Telegram",
    },
}

AUDIT_META = {
    "tracking": {"label": "رهگیری", "icon": "fa-map-marker", "tone": "tracking"},
    "inventory": {"label": "موجودی", "icon": "fa-car", "tone": "inventory"},
    "archive": {"label": "بایگانی", "icon": "fa-archive", "tone": "archive"},
    "staff": {"label": "کارکنان", "icon": "fa-shield", "tone": "staff"},
}

AUDIT_SOURCE_LABELS = {
    "system": "سیستم",
    "admin_dashboard": "پنل مدیریت",
    "backoffice": "پنل اختصاصی",
    "django_admin": "مدیریت Django",
    "telegram_bot": "ربات Telegram",
    "excel_import": "ورود Excel",
    "website": "وب‌سایت",
}


def _with_date_range(queryset, *, field_name, date_from=None, date_to=None):
    if date_from:
        queryset = queryset.filter(**{f"{field_name}__date__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{field_name}__date__lte": date_to})
    return queryset


def _audit_values(queryset, *, kind, action, subject, actor, detail):
    """Project disparate immutable event records onto a common SQL shape."""

    return queryset.annotate(
        event_id=F("pk"),
        kind=Value(kind, output_field=CharField()),
        event_action=action,
        subject=subject,
        actor=actor,
        detail=detail,
    ).values(
        "event_id",
        "created_at",
        "kind",
        "event_action",
        "source",
        "subject",
        "actor",
        "detail",
    )


def get_audit_entries(*, source="", query="", date_from=None, date_to=None):
    """Return one database-level, ordered stream of immutable audit events.

    Each source query is filtered *before* SQL UNION, so filtering and
    pagination remain database-driven instead of loading the full history into
    Python memory.
    """

    query = (query or "").strip()
    selected_sources = {source} if source else set(AUDIT_META)
    streams = []

    if "tracking" in selected_sources:
        queryset = TrackingEvent.objects.all()
        queryset = _with_date_range(
            queryset, field_name="created_at", date_from=date_from, date_to=date_to
        )
        if query:
            queryset = queryset.filter(
                Q(car__title__icontains=query)
                | Q(car__tracking_code__icontains=query)
                | Q(performed_by__username__icontains=query)
                | Q(new_stage__name__icontains=query)
                | Q(previous_stage__name__icontains=query)
            )
        streams.append(
            _audit_values(
                queryset,
                kind="tracking",
                action=F("event_type"),
                subject=F("car__title"),
                actor=Coalesce(
                    "performed_by__username",
                    Value("سیستم"),
                    output_field=CharField(),
                ),
                detail=Cast("note", output_field=CharField()),
            )
        )

    if "inventory" in selected_sources:
        queryset = VehicleInventoryEvent.objects.all()
        queryset = _with_date_range(
            queryset, field_name="created_at", date_from=date_from, date_to=date_to
        )
        if query:
            queryset = queryset.filter(
                Q(car__title__icontains=query)
                | Q(car__tracking_code__icontains=query)
                | Q(performed_by__username__icontains=query)
            )
        streams.append(
            _audit_values(
                queryset,
                kind="inventory",
                action=F("action"),
                subject=F("car__title"),
                actor=F("performed_by__username"),
                detail=Value("", output_field=CharField()),
            )
        )

    if "archive" in selected_sources:
        queryset = VehicleArchiveEvent.objects.all()
        queryset = _with_date_range(
            queryset, field_name="created_at", date_from=date_from, date_to=date_to
        )
        if query:
            queryset = queryset.filter(
                Q(car__title__icontains=query)
                | Q(car__tracking_code__icontains=query)
                | Q(performed_by__username__icontains=query)
                | Q(reason__icontains=query)
            )
        streams.append(
            _audit_values(
                queryset,
                kind="archive",
                action=F("action"),
                subject=F("car__title"),
                actor=F("performed_by__username"),
                detail=Cast("reason", output_field=CharField()),
            )
        )

    if "staff" in selected_sources:
        queryset = StaffManagementEvent.objects.all()
        queryset = _with_date_range(
            queryset, field_name="created_at", date_from=date_from, date_to=date_to
        )
        if query:
            queryset = queryset.filter(
                Q(staff_user__username__icontains=query)
                | Q(staff_user__first_name__icontains=query)
                | Q(staff_user__last_name__icontains=query)
                | Q(performed_by__username__icontains=query)
            )
        streams.append(
            _audit_values(
                queryset,
                kind="staff",
                action=F("action"),
                subject=F("staff_user__username"),
                actor=F("performed_by__username"),
                detail=Value("", output_field=CharField()),
            )
        )

    if not streams:
        return TrackingEvent.objects.none().values(
            "event_id", "created_at", "kind", "event_action", "source", "subject", "actor", "detail"
        )

    audit_query = streams[0]
    for stream in streams[1:]:
        audit_query = audit_query.union(stream, all=True)
    return audit_query.order_by("-created_at", "-event_id")


def format_audit_entry(entry):
    """Attach presentation labels without leaking storage-model details."""

    kind = entry["kind"]
    return {
        **entry,
        "title": AUDIT_LABELS.get(kind, {}).get(
            entry["event_action"], entry["event_action"]
        ),
        "source_label": AUDIT_SOURCE_LABELS.get(entry["source"], entry["source"]),
        **AUDIT_META.get(kind, {"label": kind, "icon": "fa-circle", "tone": "default"}),
    }


def get_dashboard_snapshot():
    """Return a small, query-efficient read model for the management dashboard."""

    active_cars = Car.objects.filter(is_deleted=False)
    counts = active_cars.aggregate(
        total=Count("pk"),
        for_sale=Count("pk", filter=Q(status=Car.Status.FOR_SALE)),
        on_hold=Count("pk", filter=Q(status=Car.Status.ON_HOLD)),
        pending_delivery=Count(
            "pk", filter=Q(status__in=[Car.Status.SOLD, Car.Status.IN_TRANSIT])
        ),
        delivered=Count("pk", filter=Q(status=Car.Status.DELIVERED)),
    )
    counts["new_requests"] = CustomVehicleRequest.objects.filter(
        status=CustomVehicleRequest.Status.NEW
    ).count()

    stage_rows = list(
        Stage.objects.filter(is_active=True)
        .annotate(
            vehicle_count=Count(
                "cars_at_stage",
                filter=Q(
                    cars_at_stage__is_deleted=False,
                    cars_at_stage__status__in=[Car.Status.SOLD, Car.Status.IN_TRANSIT],
                ),
            )
        )
        .order_by("order")
    )
    highest_stage_count = max((stage.vehicle_count for stage in stage_rows), default=0)
    for stage in stage_rows:
        stage.display_ratio = (
            max(8, round((stage.vehicle_count / highest_stage_count) * 100))
            if highest_stage_count
            else 0
        )

    recent_entries = [
        format_audit_entry(entry)
        for entry in get_audit_entries()[:10]
    ]

    return {
        "counts": counts,
        "stage_rows": stage_rows,
        "recent_entries": recent_entries,
    }
