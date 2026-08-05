from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render

from core.seo import breadcrumb_schema, page_context

from .public import attach_cover_photos, public_car_queryset, with_public_photos
from .spin import get_public_spin_payload


def public_vehicle_list(request):
    vehicles = with_public_photos(
        public_car_queryset().order_by("-is_featured", "-created_at")
    )
    paginator = Paginator(vehicles, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    attach_cover_photos(page_obj.object_list)

    context = {
        **page_context(
            request,
            title="خودروهای موجود برای واردات",
            description="خودروهای آمادهٔ فروش و واردات را بررسی کنید و برای دریافت مشاوره با کارشناسان تماس بگیرید.",
            canonical_path="/cars/",
            structured_data=breadcrumb_schema(
                request,
                [
                    ("صفحهٔ اصلی", "/"),
                    ("خودروهای موجود", "/cars/"),
                ],
            ),
        ),
        "page_obj": page_obj,
        "vehicles": page_obj.object_list,
    }
    return render(request, "cars/vehicle_list.html", context)


def public_vehicle_detail(request, slug, pk):
    vehicle = with_public_photos(public_car_queryset()).filter(pk=pk).first()
    if vehicle is None or vehicle.slug != slug:
        raise Http404

    attach_cover_photos([vehicle])
    vehicle_images = [photo for photo in vehicle.public_photos if photo.image]

    vehicle_schema = {
        "@context": "https://schema.org",
        "@type": "Vehicle",
        "name": vehicle.title,
        "brand": {"@type": "Brand", "name": vehicle.brand},
        "model": vehicle.model,
        "url": request.build_absolute_uri(vehicle.get_absolute_url()),
    }
    if vehicle.year:
        vehicle_schema["vehicleModelDate"] = str(vehicle.year)
    if vehicle.color:
        vehicle_schema["color"] = vehicle.color
    if vehicle.description:
        vehicle_schema["description"] = vehicle.description
    if vehicle_images:
        vehicle_schema["image"] = [
            request.build_absolute_uri(photo.image.url) for photo in vehicle_images
        ]

    context = {
        **page_context(
            request,
            title=vehicle.seo_title or vehicle.title,
            description=vehicle.seo_description or vehicle.description,
            keywords=vehicle.seo_keywords,
            canonical_path=vehicle.get_absolute_url(),
            og_image=vehicle.cover_photo.image if vehicle.cover_photo else None,
            structured_data=[
                vehicle_schema,
                breadcrumb_schema(
                    request,
                    [
                        ("صفحهٔ اصلی", "/"),
                        ("خودروهای موجود", "/cars/"),
                        (vehicle.title, vehicle.get_absolute_url()),
                    ],
                ),
            ],
        ),
        "vehicle": vehicle,
        "vehicle_images": vehicle_images,
        "vehicle_spin": get_public_spin_payload(vehicle),
    }
    return render(request, "cars/vehicle_detail.html", context)
