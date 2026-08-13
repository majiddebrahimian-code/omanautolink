from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .forms import VehicleArchiveReasonForm
from .models import Car, CarPhoto, CarSpinFrame, VehicleArchiveEvent, VehicleHold
from .services import (
    archive_vehicle,
    place_vehicle_on_hold,
    publish_vehicle_for_sale,
    release_vehicle_hold,
    restore_archived_vehicle,
)
from .spin import (
    assess_car_spin_frames,
    disable_car_spin_360,
    enable_car_spin_360,
)


ARCHIVABLE_STATUSES = {
    Car.Status.DRAFT,
    Car.Status.FOR_SALE,
}


class CarPhotoInline(admin.TabularInline):
    model = CarPhoto
    extra = 1
    readonly_fields = ["telegram_file_id"]
    fields = ["image", "is_cover", "alt_text", "sort_order", "telegram_file_id"]


class CarSpinFrameInline(admin.TabularInline):
    """Separate ordered media for the interactive 360° viewer."""

    model = CarSpinFrame
    extra = 1
    fields = ["sequence", "image", "image_width", "image_height"]
    readonly_fields = ["image_width", "image_height"]


class VehicleArchiveEventInline(admin.TabularInline):
    """Shows the immutable archive history only to the System Administrator."""

    model = VehicleArchiveEvent
    extra = 0
    can_delete = False

    fields = [
        "action",
        "previous_status",
        "new_status",
        "performed_by",
        "source",
        "reason",
        "created_at",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_or_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    change_form_template = "admin/cars/car/change_form.html"

    list_display = [
        "vehicle_code",
        "tracking_code",
        "title",
        "brand",
        "status",
        "is_deleted",
        "customer",
        "current_stage",
        "spin_360_enabled",
    ]
    list_filter = ["status", "brand", "is_featured", "is_deleted"]
    search_fields = ["vehicle_code", "tracking_code", "title", "brand", "model"]
    list_select_related = ["customer", "current_stage"]
    inlines = [CarPhotoInline, CarSpinFrameInline, VehicleArchiveEventInline]

    # Lifecycle and external-integration fields must be changed by services.
    readonly_fields = [
        "vehicle_code",
        "status",
        "tracking_code",
        "customer",
        "current_stage",
        "target_delivery",
        "channel_message_ids",
        "is_deleted",
        "spin_360_enabled",
        "spin_360_readiness",
    ]

    actions = [
        "publish_selected_cars",
        "place_selected_vehicle_on_hold",
        "enable_selected_360_views",
        "disable_selected_360_views",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "customer",
            "current_stage",
        )

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                "<path:object_id>/archive/",
                self.admin_site.admin_view(self.archive_vehicle_view),
                name="cars_car_archive",
            ),
            path(
                "<path:object_id>/restore/",
                self.admin_site.admin_view(self.restore_vehicle_view),
                name="cars_car_restore",
            ),
        ]

        return custom_urls + urls

    def get_actions(self, request):
        actions = super().get_actions(request)

        if not request.user.has_perm("cars.publish_vehicle"):
            actions.pop("publish_selected_cars", None)

        if not request.user.has_perm("cars.hold_vehicle"):
            actions.pop("place_selected_vehicle_on_hold", None)

        if not request.user.has_perm("cars.change_car"):
            actions.pop("enable_selected_360_views", None)
            actions.pop("disable_selected_360_views", None)

        return actions

    @admin.display(description="وضعیت فنی نمایش ۳۶۰")
    def spin_360_readiness(self, car):
        if not car or not car.pk:
            return "ابتدا خودرو را ذخیره کنید و سپس فریم‌ها را اضافه کنید."

        readiness = assess_car_spin_frames(car)
        if readiness.is_ready:
            quality = "پیشنهادی" if readiness.is_recommended else "پایه"
            return f"آماده برای نمایش عمومی ({readiness.frame_count} فریم؛ کیفیت {quality})"

        return "آماده نیست: " + " ".join(readiness.messages)

    def has_delete_permission(self, request, obj=None):
        """Vehicles are removed only through the audited soft-archive workflow."""

        return False

    def change_view(
        self,
        request,
        object_id,
        form_url="",
        extra_context=None,
    ):
        extra_context = extra_context or {}

        car = self.get_queryset(request).filter(pk=object_id).first()

        if car is not None:
            if (
                not car.is_deleted
                and car.status in ARCHIVABLE_STATUSES
                and request.user.has_perm("cars.archive_vehicle")
            ):
                extra_context["can_archive_vehicle"] = True
                extra_context["archive_vehicle_url"] = reverse(
                    "admin:cars_car_archive",
                    args=[car.id],
                )

            if (
                car.is_deleted
                and car.status in ARCHIVABLE_STATUSES
                and request.user.is_superuser
            ):
                extra_context["can_restore_vehicle"] = True
                extra_context["restore_vehicle_url"] = reverse(
                    "admin:cars_car_restore",
                    args=[car.id],
                )

        return super().change_view(
            request,
            object_id,
            form_url=form_url,
            extra_context=extra_context,
        )

    def archive_vehicle_view(self, request, object_id):
        car = self.get_object(request, object_id)

        if car is None:
            raise Http404

        if not (
            self.has_view_permission(request, car)
            and request.user.has_perm("cars.archive_vehicle")
        ):
            raise PermissionDenied

        return self._render_archive_operation_form(
            request,
            car,
            operation=archive_vehicle,
            title="بایگانی خودرو",
            submit_label="تأیید بایگانی خودرو",
            success_message="خودرو با موفقیت بایگانی شد.",
            notice=(
                "خودرو از موجودی فعال خارج می‌شود، اما اطلاعات و سابقهٔ آن "
                "حفظ خواهد شد."
            ),
        )

    def restore_vehicle_view(self, request, object_id):
        car = self.get_object(request, object_id)

        if car is None:
            raise Http404

        if not (
            request.user.is_superuser
            and self.has_view_permission(request, car)
        ):
            raise PermissionDenied

        return self._render_archive_operation_form(
            request,
            car,
            operation=restore_archived_vehicle,
            title="بازگردانی خودرو از بایگانی",
            submit_label="تأیید بازگردانی خودرو",
            success_message=(
                "خودرو از بایگانی بازگردانی شد و اکنون در وضعیت پیش‌نویس است."
            ),
            notice=(
                "خودرو پس از بازگردانی در وضعیت پیش‌نویس قرار می‌گیرد و "
                "برای نمایش عمومی باید جداگانه منتشر شود."
            ),
        )

    def _render_archive_operation_form(
        self,
        request,
        car,
        *,
        operation,
        title,
        submit_label,
        success_message,
        notice,
    ):
        if request.method == "POST":
            form = VehicleArchiveReasonForm(request.POST)

            if form.is_valid():
                try:
                    operation(
                        car_id=car.id,
                        actor=request.user,
                        reason=form.cleaned_data["reason"],
                        source=VehicleArchiveEvent.Source.ADMIN_DASHBOARD,
                    )
                except ValidationError as error:
                    for message in error.messages:
                        form.add_error(None, message)
                else:
                    self.log_change(
                        request,
                        car,
                        success_message,
                    )
                    self.message_user(
                        request,
                        success_message,
                        level=messages.SUCCESS,
                    )

                    return redirect(
                        "admin:cars_car_change",
                        car.id,
                    )
        else:
            form = VehicleArchiveReasonForm()

        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "opts": self.model._meta,
            "original": car,
            "car": car,
            "form": form,
            "submit_label": submit_label,
            "notice": notice,
        }

        return TemplateResponse(
            request,
            "admin/cars/car/archive_action.html",
            context,
        )

    @admin.action(description="انتشار خودروهای انتخاب‌شده برای فروش")
    def publish_selected_cars(self, request, queryset):
        success_count = 0

        for car in queryset:
            try:
                publish_vehicle_for_sale(
                    car_id=car.id,
                    actor=request.user,
                )
            except ValidationError as error:
                self.message_user(
                    request,
                    f"{car}: {' '.join(error.messages)}",
                    level=messages.ERROR,
                )
            else:
                success_count += 1

        if success_count:
            self.message_user(
                request,
                f"{success_count} خودرو برای فروش منتشر شد.",
                level=messages.SUCCESS,
            )

    @admin.action(description="فعال‌سازی نمایش ۳۶۰ برای خودروهای انتخاب‌شده")
    def enable_selected_360_views(self, request, queryset):
        enabled_count = 0

        for car in queryset:
            try:
                enable_car_spin_360(car_id=car.id, actor=request.user)
            except ValidationError as error:
                self.message_user(
                    request,
                    f"{car}: {' '.join(error.messages)}",
                    level=messages.ERROR,
                )
            else:
                enabled_count += 1

        if enabled_count:
            self.message_user(
                request,
                f"نمایش ۳۶۰ برای {enabled_count} خودرو فعال شد.",
                level=messages.SUCCESS,
            )

    @admin.action(description="غیرفعال‌سازی نمایش ۳۶۰ برای خودروهای انتخاب‌شده")
    def disable_selected_360_views(self, request, queryset):
        disabled_count = 0

        for car in queryset:
            try:
                disable_car_spin_360(car_id=car.id, actor=request.user)
            except ValidationError as error:
                self.message_user(
                    request,
                    f"{car}: {' '.join(error.messages)}",
                    level=messages.ERROR,
                )
            else:
                disabled_count += 1

        if disabled_count:
            self.message_user(
                request,
                f"نمایش ۳۶۰ برای {disabled_count} خودرو غیرفعال شد.",
                level=messages.SUCCESS,
            )

    @admin.action(description="رزرو موقت خودروی انتخاب‌شده")
    def place_selected_vehicle_on_hold(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                "برای رزرو موقت باید دقیقاً یک خودرو انتخاب کنید.",
                level=messages.ERROR,
            )
            return

        car = queryset.first()

        try:
            place_vehicle_on_hold(
                car_id=car.id,
                actor=request.user,
            )
        except ValidationError as error:
            self.message_user(
                request,
                " ".join(error.messages),
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                f"{car} با موفقیت رزرو موقت شد.",
                level=messages.SUCCESS,
            )


@admin.register(VehicleArchiveEvent)
class VehicleArchiveEventAdmin(admin.ModelAdmin):
    list_display = [
        "car",
        "action",
        "previous_status",
        "new_status",
        "performed_by",
        "source",
        "created_at",
    ]
    list_filter = ["action", "source", "created_at"]
    search_fields = [
        "car__vehicle_code",
        "car__tracking_code",
        "car__title",
        "performed_by__username",
        "reason",
    ]
    list_select_related = ["car", "performed_by"]
    ordering = ["-created_at", "-pk"]
    date_hierarchy = "created_at"

    readonly_fields = [
        "car",
        "action",
        "previous_status",
        "new_status",
        "performed_by",
        "source",
        "reason",
        "created_at",
    ]

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VehicleHold)
class VehicleHoldAdmin(admin.ModelAdmin):
    list_display = [
        "car",
        "customer_name",
        "customer_phone",
        "created_by",
        "created_at",
        "expires_at",
        "is_active",
        "released_by",
        "released_at",
    ]
    list_filter = ["is_active", "created_at"]
    search_fields = [
        "car__title",
        "car__vehicle_code",
        "car__tracking_code",
        "customer_name",
        "customer_phone",
    ]
    list_select_related = ["car", "created_by", "released_by"]

    readonly_fields = [
        "car",
        "customer_name",
        "customer_phone",
        "created_by",
        "created_at",
        "expires_at",
        "is_active",
        "released_at",
        "released_by",
        "release_note",
    ]

    actions = ["release_selected_holds"]

    def get_actions(self, request):
        actions = super().get_actions(request)

        if not request.user.has_perm("cars.release_vehicle_hold"):
            actions.pop("release_selected_holds", None)

        return actions

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="آزادسازی رزروهای انتخاب‌شده")
    def release_selected_holds(self, request, queryset):
        success_count = 0

        for hold in queryset:
            try:
                release_vehicle_hold(
                    hold_id=hold.id,
                    actor=request.user,
                    release_note="آزادسازی از طریق پنل مدیریت.",
                )
            except ValidationError as error:
                self.message_user(
                    request,
                    f"{hold}: {' '.join(error.messages)}",
                    level=messages.ERROR,
                )
            else:
                success_count += 1

        if success_count:
            self.message_user(
                request,
                f"{success_count} رزرو موقت آزاد شد.",
                level=messages.SUCCESS,
            )
