"""Query helpers for public inventory pages.

These helpers deliberately keep public visibility rules out of templates so
that the homepage, inventory list, sitemap, and vehicle detail pages agree on
which vehicles may be exposed.
"""

from django.db.models import Prefetch

from .models import Car, CarPhoto


def public_car_queryset():
    return Car.objects.filter(
        status=Car.Status.FOR_SALE,
        is_deleted=False,
    )


def with_public_photos(queryset):
    return queryset.prefetch_related(
        Prefetch(
            "photos",
            queryset=CarPhoto.objects.exclude(image="").order_by(
                "-is_cover",
                "sort_order",
                "pk",
            ),
            to_attr="public_photos",
        )
    )


def attach_cover_photos(cars):
    """Attach a non-persistent cover-photo attribute for simple templates."""

    for car in cars:
        public_photos = getattr(car, "public_photos", [])
        car.cover_photo = next(
            (photo for photo in public_photos if photo.image),
            None,
        )

    return cars
