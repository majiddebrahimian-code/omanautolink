"""Shared public inventory search and filter helpers.

Both the vehicle-list page and the home-page search form use this module so
their available filters and query semantics stay consistent.
"""

from decimal import Decimal, InvalidOperation

from django.db.models import Max, Min, Q


SORT_OPTIONS = {
    "newest": ("-is_featured", "-created_at"),
    "price_asc": ("price_amount", "-created_at"),
    "price_desc": ("-price_amount", "-created_at"),
    "year_desc": ("-year", "-created_at"),
}


def _positive_integer(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _positive_decimal(value):
    try:
        value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value >= 0 else None


def public_inventory_filter_options(queryset, *, selected_brand=""):
    """Return only values that really exist in the currently public inventory."""

    base_queryset = queryset
    model_queryset = base_queryset
    if selected_brand:
        model_queryset = model_queryset.filter(brand__iexact=selected_brand)

    ranges = base_queryset.aggregate(min_price=Min("price_amount"), max_price=Max("price_amount"))
    return {
        "brands": list(base_queryset.exclude(brand="").order_by("brand").values_list("brand", flat=True).distinct()),
        "models": list(model_queryset.exclude(model="").order_by("model").values_list("model", flat=True).distinct()),
        "colors": list(base_queryset.exclude(color="").order_by("color").values_list("color", flat=True).distinct()),
        "years": list(base_queryset.exclude(year__isnull=True).order_by("-year").values_list("year", flat=True).distinct()),
        "min_price": ranges["min_price"] or 0,
        "max_price": ranges["max_price"] or 0,
    }


def apply_public_inventory_filters(queryset, raw_filters):
    """Filter a public queryset and return it with cleaned values for templates."""

    filters = {
        "q": (raw_filters.get("q") or "").strip(),
        "brand": (raw_filters.get("brand") or "").strip(),
        "model": (raw_filters.get("model") or "").strip(),
        "color": (raw_filters.get("color") or "").strip(),
        "year_min": _positive_integer(raw_filters.get("year_min")),
        "year_max": _positive_integer(raw_filters.get("year_max")),
        "price_min": _positive_decimal(raw_filters.get("price_min")),
        "price_max": _positive_decimal(raw_filters.get("price_max")),
        "sort": (raw_filters.get("sort") or "newest").strip(),
    }
    if filters["sort"] not in SORT_OPTIONS:
        filters["sort"] = "newest"

    if filters["q"]:
        query = filters["q"]
        queryset = queryset.filter(
            Q(vehicle_code__icontains=query)
            | Q(title__icontains=query)
            | Q(brand__icontains=query)
            | Q(model__icontains=query)
            | Q(color__icontains=query)
        )
    for field in ("brand", "model", "color"):
        if filters[field]:
            queryset = queryset.filter(**{f"{field}__iexact": filters[field]})
    if filters["year_min"] is not None:
        queryset = queryset.filter(year__gte=filters["year_min"])
    if filters["year_max"] is not None:
        queryset = queryset.filter(year__lte=filters["year_max"])
    if filters["price_min"] is not None:
        queryset = queryset.filter(price_amount__gte=filters["price_min"])
    if filters["price_max"] is not None:
        queryset = queryset.filter(price_amount__lte=filters["price_max"])

    return queryset.order_by(*SORT_OPTIONS[filters["sort"]]), filters