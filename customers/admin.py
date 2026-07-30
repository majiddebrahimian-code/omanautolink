from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .forms import AdminCustomVehicleRequestConversionForm
from .models import (
    Customer,
    CustomVehicleRequest,
    CustomVehicleRequestReadReceipt,
    SearchLog,
)
from .services import (
    convert_custom_vehicle_request_to_sold,
    record_custom_vehicle_request_view,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["full_name", "phone", "telegram_id"]
    search_fields = ["full_name", "phone", "telegram_id"]


@admin.register(SearchLog)
class SearchLogAdmin(admin.ModelAdmin):
    list_display = ["source", "car", "customer", "searched_at"]
    list_filter = ["source"]
    search_fields = ["car__tracking_code", "customer__full_name"]
    readonly_fields = [
        "car",
        "customer",
        "source",
        "user_agent",
        "searched_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CustomVehicleRequestReadReceiptInline(admin.TabularInline):
    model = CustomVehicleRequestReadReceipt
    extra = 0
    can_delete = False

    fields = [
        "employee",
        "first_seen_at",
        "last_seen_at",
    ]
    readonly_fields = [
        "employee",
        "first_seen_at",
        "last_seen_at",
    ]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_or_change_permission(self, request, obj=None):
        return request.user.has_perm("customers.view_customvehiclerequest")


@admin.register(CustomVehicleRequest)
class CustomVehicleRequestAdmin(admin.ModelAdmin):
    change_form_template = "admin/customers/customvehiclerequest/change_form.html"

    list_display = [
        "id",
        "full_name",
        "phone",
        "source",
        "status",
        "sold_car",
        "created_at",
    ]
    list_filter = [
        "source",
        "status",
        "created_at",
    ]
    search_fields = [
        "full_name",
        "phone",
        "telegram_id",
        "preferred_brand",
        "preferred_model",
        "desired_vehicle_description",
    ]
    date_hierarchy = "created_at"
    list_select_related = [
        "sold_car",
        "sold_by",
    ]

    readonly_fields = [
        "full_name",
        "phone",
        "telegram_id",
        "desired_vehicle_description",
        "preferred_brand",
        "preferred_model",
        "preferred_year_from",
        "preferred_year_to",
        "budget_amount",
        "preferred_color",
        "notes",
        "source",
        "status",
        "sold_car",
        "sold_at",
        "sold_by",
        "created_at",
        "updated_at",
    ]

    fieldsets = [
        (
            "اطلاعات مشتری",
            {
                "fields": [
                    "full_name",
                    "phone",
                    "telegram_id",
                ]
            },
        ),
        (
            "خودروی موردنظر مشتری",
            {
                "fields": [
                    "desired_vehicle_description",
                    "preferred_brand",
                    "preferred_model",
                    "preferred_year_from",
                    "preferred_year_to",
                    "budget_amount",
                    "preferred_color",
                    "notes",
                ]
            },
        ),
        (
            "وضعیت درخواست",
            {
                "fields": [
                    "source",
                    "status",
                    "sold_car",
                    "sold_at",
                    "sold_by",
                    "created_at",
                    "updated_at",
                ]
            },
        ),
    ]

    inlines = [
        CustomVehicleRequestReadReceiptInline,
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "sold_car",
                "sold_by",
            )
        )

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<path:object_id>/convert-to-sale/",
                self.admin_site.admin_view(self.convert_to_sale_view),
                name=("customers_customvehiclerequest_convert_to_sale"),
            ),
        ]

        return custom_urls + urls

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def change_view(
        self,
        request,
        object_id,
        form_url="",
        extra_context=None,
    ):
        extra_context = extra_context or {}

        vehicle_request = self.get_queryset(request).filter(pk=object_id).first()

        if (
            vehicle_request is not None
            and request.user.is_authenticated
            and request.user.has_perm("customers.view_customvehiclerequest")
        ):
            record_custom_vehicle_request_view(
                vehicle_request_id=vehicle_request.id,
                employee=request.user,
            )

            if (
                vehicle_request.status == CustomVehicleRequest.Status.NEW
                and request.user.has_perm(
                    "customers.convert_custom_vehicle_request_to_sale"
                )
                and request.user.has_perm("cars.sell_vehicle")
            ):
                extra_context["can_convert_to_sale"] = True
                extra_context["convert_to_sale_url"] = reverse(
                    "admin:customers_customvehiclerequest_convert_to_sale",
                    args=[vehicle_request.id],
                )

        return super().change_view(
            request,
            object_id,
            form_url=form_url,
            extra_context=extra_context,
        )

    def convert_to_sale_view(self, request, object_id):
        vehicle_request = self.get_object(request, object_id)

        if vehicle_request is None:
            raise Http404

        if not (
            request.user.has_perm("customers.view_customvehiclerequest")
            and request.user.has_perm(
                "customers.convert_custom_vehicle_request_to_sale"
            )
            and request.user.has_perm("cars.sell_vehicle")
        ):
            raise PermissionDenied

        record_custom_vehicle_request_view(
            vehicle_request_id=vehicle_request.id,
            employee=request.user,
        )

        if vehicle_request.status != CustomVehicleRequest.Status.NEW:
            self.message_user(
                request,
                "این درخواست قبلاً به فروش تبدیل شده است.",
                level=messages.ERROR,
            )

            return redirect(
                "admin:customers_customvehiclerequest_change",
                vehicle_request.id,
            )

        if request.method == "POST":
            form = AdminCustomVehicleRequestConversionForm(request.POST)

            if form.is_valid():
                try:
                    sold_car = convert_custom_vehicle_request_to_sold(
                        vehicle_request_id=vehicle_request.id,
                        car_id=form.cleaned_data["car"].id,
                        actor=request.user,
                        telegram_id=form.cleaned_data["telegram_id"],
                    )
                except ValidationError as error:
                    for message in error.messages:
                        form.add_error(None, message)
                else:
                    self.message_user(
                        request,
                        (
                            "درخواست با موفقیت به فروش تبدیل شد. "
                            f"کد رهگیری خودرو: {sold_car.tracking_code}\n"
                            "کد فعال‌سازی ربات مشتری (فقط همین یک‌بار نمایش داده "
                            "می‌شود): "
                            f"{sold_car.telegram_customer_activation_code}"
                        ),
                        level=messages.SUCCESS,
                    )

                    return redirect(
                        "admin:customers_customvehiclerequest_change",
                        vehicle_request.id,
                    )
        else:
            form = AdminCustomVehicleRequestConversionForm(
                initial={
                    "telegram_id": vehicle_request.telegram_id,
                }
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "تبدیل درخواست به فروش",
            "opts": self.model._meta,
            "original": vehicle_request,
            "form": form,
        }

        return TemplateResponse(
            request,
            ("admin/customers/customvehiclerequest/" "convert_to_sale.html"),
            context,
        )
