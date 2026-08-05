from django import template

from cars.models import Car

register = template.Library()


CAR_STATUS_META = {
    Car.Status.DRAFT: {
        "label": "پیش‌نویس",
        "tone": "draft",
    },
    Car.Status.FOR_SALE: {
        "label": "آمادهٔ فروش",
        "tone": "sale",
    },
    Car.Status.ON_HOLD: {
        "label": "رزرو موقت",
        "tone": "hold",
    },
    Car.Status.SOLD: {
        "label": "فروخته‌شده",
        "tone": "sold",
    },
    Car.Status.IN_TRANSIT: {
        "label": "در مسیر تحویل",
        "tone": "transit",
    },
    Car.Status.DELIVERED: {
        "label": "تحویل‌داده‌شده",
        "tone": "delivered",
    },
}


@register.filter
def car_status_label(status):
    return CAR_STATUS_META.get(
        status,
        {"label": "نامشخص"},
    )["label"]


@register.filter
def car_status_tone(status):
    return CAR_STATUS_META.get(
        status,
        {"tone": "draft"},
    )["tone"]
