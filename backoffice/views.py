from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model, logout
from datetime import date
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import (
    BooleanField,
    Case,
    Count,
    Exists,
    OuterRef,
    Prefetch,
    Q,
    Value,
    When,
)
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.forms import (
    StaffAccountForm,
    StaffPasswordResetForm,
    StaffStatusChangeForm,
    StaffTelegramRevokeForm,
)
from accounts.models import StaffManagementEvent, StaffProfile
from accounts.services import (
    RoleGroup,
    StaffBusinessRole,
    create_staff_member,
    get_assignable_exception_permissions,
    get_exception_permission_details,
    get_staff_business_role,
    get_staff_business_role_label,
    issue_staff_telegram_link_code,
    reset_staff_password,
    revoke_staff_telegram_link,
    set_staff_active_state,
    update_staff_member,
)
from blog.forms import BlogPostForm
from blog.models import Post
from blog.services import (
    create_post,
    delete_post,
    publish_post,
    unpublish_post,
    update_post,
)
from cars.forms import (
    CarInventoryForm,
    CarPhotoMetadataForm,
    CarPhotoUploadForm,
    CarVideoUploadForm,
    VehicleArchiveReasonForm,
    VehicleHoldCreateForm,
    VehicleHoldReleaseForm,
    VehicleSaleForm,
    VehicleSaleReversalForm,
)
from cars.models import (
    Car,
    CarPhoto,
    CarVideo,
    VehicleArchiveEvent,
    VehicleHold,
    VehicleInventoryEvent,
)
from cars.services import (
    INVENTORY_EDITABLE_STATUSES,
    archive_vehicle,
    create_inventory_car,
    create_inventory_car_and_publish_to_telegram,
    delete_car_photo,
    mark_vehicle_as_sold,
    place_vehicle_on_hold,
    publish_vehicle_for_sale,
    release_vehicle_hold,
    get_vehicle_sale_reversal_eligibility,
    reverse_vehicle_sale,
    set_car_photo_cover,
    update_car_photo_metadata,
    update_inventory_car,
    update_inventory_car_and_publish_to_telegram,
    upload_car_photos,
    upload_car_video,
)
from core.forms import (
    FooterLinkForm,
    FooterSectionForm,
    HeaderNavigationItemForm,
    HomeFeatureCardForm,
    HomePageConfigurationForm,
    HomeQuickActionForm,
    SeoConfigurationForm,
    SiteIdentityForm,
    SocialLinkForm,
    StaticPageForm,
)
from core.models import (
    FooterLink,
    FooterSection,
    HeaderNavigationItem,
    HomeFeatureCard,
    HomePageConfiguration,
    HomeQuickAction,
    SeoConfiguration,
    SiteConfiguration,
    SocialLink,
    StaticPage,
)
from core.site_services import (
    create_site_collection_item,
    delete_site_collection_item,
    update_home_page_configuration,
    update_site_collection_item,
    update_site_identity_and_seo,
)
from customers.forms import AdminCustomVehicleRequestConversionForm
from customers.models import Customer, CustomVehicleRequest, CustomVehicleRequestReadReceipt
from customers.services import (
    convert_custom_vehicle_request_to_sold,
    record_custom_vehicle_request_view,
)
from integrations.models import (
    CustomerTelegramSubscription,
    TelegramChannel,
    TelegramInboundUpdate,
    TelegramOutboxMessage,
    TelegramStaffLink,
    TelegramStaffLinkToken,
    TelegramVehiclePublication,
)
from integrations.forms import TelegramChannelForm, TelegramIntegrationSettingsForm
from integrations.services import (
    get_telegram_integration_settings,
    queue_vehicle_channel_sale_state_change,
    retry_failed_telegram_outbox_message,
    test_telegram_bot_connection,
    test_telegram_channel_access,
    update_telegram_integration_settings,
)
from tracking.forms import (
    ClearanceConfirmationForm,
    ClearanceTrackingCodeForm,
    StageArchiveForm,
    StageDefinitionForm,
    TrackingImportUploadForm,
    TransitionRepairForm,
)
from tracking.models import (
    CarStageProgress,
    Stage,
    StageTransition,
    TrackingEvent,
    TrackingImportJob,
    TrackingImportRow,
)
from tracking.imports import create_tracking_import_job
from tracking.services import (
    archive_stage,
    complete_stage,
    confirm_stage,
    create_linear_stage,
    get_delivery_machine_snapshot,
    get_linear_stage_route_integrity,
    get_stage_archive_impact,
    get_stage_completion_preview,
    get_stage_confirmation_preview,
    get_clearance_work_queue,
    get_completed_clearance_history,
    repair_linear_stage_transitions,
    update_linear_stage,
)

from .access import (
    panel_permissions_required,
    system_administrator_required,
)
from .forms import AuditLogFilterForm
from .reporting import format_audit_entry, get_audit_entries, get_dashboard_snapshot


@require_POST
def panel_logout(request):
    """End a panel session through a CSRF-protected, fixed redirect flow."""

    logout(request)
    messages.info(request, "از پنل مدیریت خارج شدید.")
    return redirect("admin:login")


def _render_placeholder(request, *, title, description):
    return render(
        request,
        "backoffice/placeholder.html",
        {
            "title": title,
            "description": description,
        },
    )


def _add_service_errors(form, error):
    """Expose a domain-validation error on the form without duplicating it."""

    for message in error.messages:
        form.add_error(None, message)


PAGINATION_SIZE_OPTIONS = (10, 20, 50, 100, 150)


def _get_requested_per_page(request, *, default=20):
    """Accept only administrator-approved list sizes from the query string."""
    try:
        selected_size = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return selected_size if selected_size in PAGINATION_SIZE_OPTIONS else default


def _get_paginated_context(*, request, queryset, search_fields, per_page=20):
    """Apply a stable ``q`` search and pagination to an internal list."""

    query = (request.GET.get("q") or "").strip()

    if query:
        search_condition = Q()

        for field_name in search_fields:
            search_condition |= Q(**{f"{field_name}__icontains": query})

        queryset = queryset.filter(search_condition)

    paginator = Paginator(queryset, _get_requested_per_page(request, default=per_page))
    page_obj = paginator.get_page(request.GET.get("page"))

    return {
        "page_obj": page_obj,
        "query": query,
        "result_count": paginator.count,
    }


def _active_machine_queryset():
    """Return active inventory rows with UI-only eligibility annotations."""

    active_hold_query = VehicleHold.objects.filter(
        car_id=OuterRef("pk"),
        is_active=True,
    )

    telegram_publication_query = TelegramVehiclePublication.objects.filter(
        car_id=OuterRef("pk"),
    )
    telegram_published_query = telegram_publication_query.filter(
        telegram_message_id__isnull=False,
    )
    telegram_pending_query = telegram_publication_query.filter(
        latest_outbox_message__status__in=[
            TelegramOutboxMessage.Status.PENDING,
            TelegramOutboxMessage.Status.SENDING,
            TelegramOutboxMessage.Status.RETRY,
        ],
    )
    telegram_failed_query = telegram_publication_query.filter(
        latest_outbox_message__status=TelegramOutboxMessage.Status.FAILED,
    )

    return (
        Car.objects.filter(is_deleted=False)
        .select_related("customer", "current_stage")
        .prefetch_related(
            Prefetch(
                "telegram_publications",
                queryset=TelegramVehiclePublication.objects.select_related(
                    "latest_outbox_message",
                    "channel",
                ).order_by("-updated_at", "-pk"),
                to_attr="telegram_publications_for_panel",
            )
        )
        .annotate(
            has_active_hold=Exists(active_hold_query),
            has_telegram_publication=Exists(telegram_publication_query),
            has_telegram_publication_success=Exists(telegram_published_query),
            has_telegram_publication_pending=Exists(telegram_pending_query),
            has_telegram_publication_failed=Exists(telegram_failed_query),
            inventory_fields_editable=Case(
                When(
                    status__in=INVENTORY_EDITABLE_STATUSES,
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            ),
            photo_count=Count("photos", distinct=True),
        )
        .order_by("-created_at")
    )


def _get_machine_list_context(request, *, queryset):
    selected_status = (request.GET.get("status") or "").strip()
    selected_telegram = (request.GET.get("telegram") or "").strip()

    if selected_status in set(Car.Status.values):
        queryset = queryset.filter(status=selected_status)

    if selected_telegram == "published":
        queryset = queryset.filter(has_telegram_publication_success=True)
    elif selected_telegram == "pending":
        queryset = queryset.filter(has_telegram_publication_pending=True)
    elif selected_telegram == "failed":
        queryset = queryset.filter(has_telegram_publication_failed=True)
    elif selected_telegram == "not_published":
        queryset = queryset.filter(has_telegram_publication=False)

    context = _get_paginated_context(
        request=request,
        queryset=queryset,
        search_fields=(
            "title",
            "brand",
            "model",
            "vehicle_code",
            "tracking_code",
            "customer__full_name",
        ),
    )
    _decorate_machine_telegram_states(context["page_obj"].object_list)
    context.update(
        {
            "selected_status": selected_status,
            "selected_telegram": selected_telegram,
        }
    )
    return context


def _decorate_machine_telegram_states(machines):
    """Attach the latest channel-sync state for the list view only."""

    labels = {
        TelegramOutboxMessage.Status.PENDING: ("در صف ارسال", "pending", "fa-clock-o"),
        TelegramOutboxMessage.Status.SENDING: ("در حال ارسال", "pending", "fa-refresh"),
        TelegramOutboxMessage.Status.RETRY: ("در انتظار تلاش مجدد", "retry", "fa-repeat"),
        TelegramOutboxMessage.Status.FAILED: ("ناموفق", "failed", "fa-exclamation-triangle"),
    }
    for machine in machines:
        publication = next(
            iter(getattr(machine, "telegram_publications_for_panel", [])),
            None,
        )
        latest_outbox = publication.latest_outbox_message if publication else None

        if latest_outbox and latest_outbox.status in labels:
            label, tone, icon = labels[latest_outbox.status]
        elif publication and publication.telegram_message_id:
            label, tone, icon = "منتشرشده", "published", "fa-paper-plane"
        else:
            label, tone, icon = "منتشر نشده", "not-published", "fa-paper-plane-o"

        machine.telegram_publication = publication
        machine.telegram_publication_label = label
        machine.telegram_publication_tone = tone
        machine.telegram_publication_icon = icon


@staff_member_required
def dashboard(request):
    context = {"management_snapshot": None, "clearance_queue": None}
    if request.user.is_superuser:
        context["management_snapshot"] = get_dashboard_snapshot()
    elif request.user.has_perm("tracking.confirm_tracking_stage"):
        context["clearance_queue"] = get_clearance_work_queue(staff=request.user)
    return render(request, "backoffice/dashboard.html", context)


# ---------------------------------------------------------------------------
# Telegram operations console
# ---------------------------------------------------------------------------


_TELEGRAM_OUTBOX_STATUS_LABELS = {
    TelegramOutboxMessage.Status.PENDING: "در صف ارسال",
    TelegramOutboxMessage.Status.SENDING: "در حال ارسال",
    TelegramOutboxMessage.Status.SENT: "ارسال‌شده",
    TelegramOutboxMessage.Status.RETRY: "در انتظار تلاش مجدد",
    TelegramOutboxMessage.Status.FAILED: "ناموفق",
}
_TELEGRAM_INBOUND_STATUS_LABELS = {
    TelegramInboundUpdate.Status.RECEIVED: "دریافت‌شده",
    TelegramInboundUpdate.Status.PROCESSED: "پردازش‌شده",
    TelegramInboundUpdate.Status.FAILED: "ناموفق",
}


@system_administrator_required
def telegram_management(request):
    """Operational overview only; Bot secrets remain environment-owned."""

    outbox_messages = list(
        TelegramOutboxMessage.objects.select_related(
            "staff_link__user",
            "customer_subscription__customer",
            "customer_subscription__car",
        ).order_by("-created_at", "-pk")[:12]
    )
    for message in outbox_messages:
        message.panel_status_label = _TELEGRAM_OUTBOX_STATUS_LABELS.get(
            message.status,
            message.status,
        )

    inbound_updates = list(
        TelegramInboundUpdate.objects.select_related(
            "staff_link__user",
            "customer_subscription__customer",
        ).order_by("-received_at", "-pk")[:10]
    )
    for update in inbound_updates:
        update.panel_status_label = _TELEGRAM_INBOUND_STATUS_LABELS.get(
            update.status,
            update.status,
        )

    return render(
        request,
        "backoffice/telegram/dashboard.html",
        {
            "bot_is_enabled": bool(settings.TELEGRAM_BOT_ENABLED),
            "bot_token_is_configured": bool(settings.TELEGRAM_BOT_TOKEN),
            "webhook_secret_is_configured": bool(settings.TELEGRAM_WEBHOOK_SECRET),
            "outbox_counts": {
                "pending": TelegramOutboxMessage.objects.filter(
                    status=TelegramOutboxMessage.Status.PENDING
                ).count(),
                "retry": TelegramOutboxMessage.objects.filter(
                    status=TelegramOutboxMessage.Status.RETRY
                ).count(),
                "failed": TelegramOutboxMessage.objects.filter(
                    status=TelegramOutboxMessage.Status.FAILED
                ).count(),
                "sent": TelegramOutboxMessage.objects.filter(
                    status=TelegramOutboxMessage.Status.SENT
                ).count(),
            },
            "connected_staff_count": TelegramStaffLink.objects.filter(
                is_active=True,
            ).count(),
            "customer_subscription_count": CustomerTelegramSubscription.objects.filter(
                is_active=True,
            ).count(),
            "failed_inbound_count": TelegramInboundUpdate.objects.filter(
                status=TelegramInboundUpdate.Status.FAILED,
            ).count(),
            "outbox_messages": outbox_messages,
            "inbound_updates": inbound_updates,
            "connected_staff": TelegramStaffLink.objects.filter(
                is_active=True,
            ).select_related("user").order_by("-last_seen_at", "-linked_at")[:6],
            "customer_subscriptions": CustomerTelegramSubscription.objects.filter(
                is_active=True,
            ).select_related("customer", "car").order_by("-last_seen_at", "-subscribed_at")[:6],
        },
    )


@system_administrator_required
def telegram_settings(request):
    settings_record = get_telegram_integration_settings()
    if request.method == "POST":
        form = TelegramIntegrationSettingsForm(request.POST, instance=settings_record)
        if form.is_valid():
            try:
                update_telegram_integration_settings(
                    actor=request.user,
                    settings_data=form.cleaned_data,
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(request, "تنظیمات عملیاتی Telegram ذخیره شد.")
                return redirect("backoffice:telegram_settings")
    else:
        form = TelegramIntegrationSettingsForm(instance=settings_record)

    return render(
        request,
        "backoffice/telegram/settings.html",
        {
            "form": form,
            "bot_token_is_configured": bool(settings.TELEGRAM_BOT_TOKEN),
            "webhook_secret_is_configured": bool(settings.TELEGRAM_WEBHOOK_SECRET),
        },
    )


@system_administrator_required
def telegram_channel_list(request):
    from integrations.models import TelegramChannel

    return render(
        request,
        "backoffice/telegram/channels.html",
        {"channels": TelegramChannel.objects.all()},
    )


@system_administrator_required
def telegram_channel_create(request):
    if request.method == "POST":
        form = TelegramChannelForm(request.POST)
        if form.is_valid():
            channel = form.save(commit=False)
            channel.full_clean()
            channel.save()
            messages.success(request, f"کانال «{channel.name}» ثبت شد.")
            return redirect("backoffice:telegram_channel_list")
    else:
        form = TelegramChannelForm()

    return render(
        request,
        "backoffice/telegram/channel_form.html",
        {"form": form, "channel": None, "page_title": "افزودن کانال Telegram"},
    )


@system_administrator_required
def telegram_channel_edit(request, pk):
    from integrations.models import TelegramChannel

    channel = get_object_or_404(TelegramChannel, pk=pk)
    if request.method == "POST":
        form = TelegramChannelForm(request.POST, instance=channel)
        if form.is_valid():
            channel = form.save(commit=False)
            channel.full_clean()
            channel.save()
            messages.success(request, f"کانال «{channel.name}» به‌روزرسانی شد.")
            return redirect("backoffice:telegram_channel_list")
    else:
        form = TelegramChannelForm(instance=channel)

    return render(
        request,
        "backoffice/telegram/channel_form.html",
        {"form": form, "channel": channel, "page_title": "ویرایش کانال Telegram"},
    )


@require_POST
@system_administrator_required
def telegram_bot_connection_test(request):
    """Run a safe getMe readiness check; credentials never reach the response."""
    try:
        result = test_telegram_bot_connection(actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        display_name = f"@{result['username']}" if result["username"] else result["first_name"]
        messages.success(request, f"ارتباط با Bot تلگرام {display_name or 'تنظیم‌شده'} برقرار است.")
    return redirect("backoffice:telegram_management")


@require_POST
@system_administrator_required
def telegram_channel_access_test(request, pk):
    """Check the Bot's real posting privileges for one configured channel."""
    try:
        result = test_telegram_channel_access(actor=request.user, channel_id=pk)
    except TelegramChannel.DoesNotExist:
        raise Http404("کانال Telegram پیدا نشد.")
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        channel = result["channel"]
        if result["is_fully_ready"]:
            messages.success(
                request,
                f"دسترسی Bot به کانال «{channel.name}» کامل است: ارسال، ویرایش و حذف پست.",
            )
        else:
            messages.warning(
                request,
                f"Bot می‌تواند در کانال «{channel.name}» پست بگذارد، اما دسترسی ویرایش یا حذف کامل نیست.",
            )
    return redirect("backoffice:telegram_channel_list")


@require_POST
@system_administrator_required
def telegram_outbox_retry(request, pk):
    try:
        retry_failed_telegram_outbox_message(outbox_id=pk, actor=request.user)
    except TelegramOutboxMessage.DoesNotExist:
        raise Http404("پیام Telegram پیدا نشد.")
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "پیام Telegram برای ارسال مجدد در صف قرار گرفت.")

    return redirect("backoffice:telegram_management")


@system_administrator_required
def audit_log(request):
    """Read-only audit timeline with validated, database-side filters."""

    form = AuditLogFilterForm(request.GET or None)
    if form.is_valid():
        entries = get_audit_entries(
            source=form.cleaned_data["source"],
            query=form.cleaned_data["q"],
            date_from=form.cleaned_data["date_from"],
            date_to=form.cleaned_data["date_to"],
        )
    else:
        entries = get_audit_entries()

    paginator = Paginator(entries, _get_requested_per_page(request, default=20))
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = [
        format_audit_entry(entry) for entry in page_obj.object_list
    ]

    return render(
        request,
        "backoffice/reports/audit_log.html",
        {
            "form": form,
            "page_obj": page_obj,
            "result_count": paginator.count,
        },
    )


@panel_permissions_required("cars.view_car")
def machine_list(request):
    context = _get_machine_list_context(
        request,
        queryset=_active_machine_queryset(),
    )

    return render(request, "backoffice/machines/list.html", context)


@panel_permissions_required("cars.add_car")
def machine_create(request):
    if request.method == "POST":
        form = CarInventoryForm(request.POST)

        if form.is_valid():
            try:
                publish_to_telegram = (
                    request.POST.get("submit_action") == "publish_to_telegram"
                )
                if publish_to_telegram:
                    car, _publication, _outbox_message = (
                        create_inventory_car_and_publish_to_telegram(
                            actor=request.user,
                            vehicle_data=form.cleaned_data,
                            source=VehicleInventoryEvent.Source.BACKOFFICE,
                        )
                    )
                else:
                    car = create_inventory_car(
                        actor=request.user,
                        vehicle_data=form.cleaned_data,
                        source=VehicleInventoryEvent.Source.BACKOFFICE,
                    )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                if publish_to_telegram:
                    messages.success(
                        request,
                        f"ماشین «{car.title}» منتشر و در صف ارسال به Telegram قرار گرفت.",
                    )
                else:
                    messages.success(
                        request,
                        f"ماشین «{car.title}» به‌صورت پیش‌نویس ثبت شد.",
                    )
                return redirect("backoffice:machine_list")
    else:
        form = CarInventoryForm()

    return render(
        request,
        "backoffice/machines/form.html",
        {
            "form": form,
            "machine": None,
            "form_title": "ثبت ماشین جدید",
            "submit_label": "ثبت پیش‌نویس ماشین",
            "notice": (
                "ماشین ابتدا به‌صورت پیش‌نویس ذخیره می‌شود. انتشار، رزرو و فروش "
                "عملیات جداگانه و قابل رهگیری هستند."
            ),
            "can_publish_to_telegram": request.user.has_perm("cars.publish_vehicle"),
        },
    )


@panel_permissions_required("cars.change_car")
def machine_edit(request, pk):
    machine = get_object_or_404(
        Car.objects.prefetch_related("photos", "videos"),
        pk=pk,
        is_deleted=False,
    )

    if request.method == "POST":
        form = CarInventoryForm(request.POST, instance=machine)

        if form.is_valid():
            try:
                publish_to_telegram = (
                    request.POST.get("submit_action") == "publish_to_telegram"
                )
                if publish_to_telegram:
                    updated_machine, _publication, _outbox_message = (
                        update_inventory_car_and_publish_to_telegram(
                            car_id=machine.id,
                            actor=request.user,
                            vehicle_data=form.cleaned_data,
                            source=VehicleInventoryEvent.Source.BACKOFFICE,
                        )
                    )
                else:
                    updated_machine = update_inventory_car(
                        car_id=machine.id,
                        actor=request.user,
                        vehicle_data=form.cleaned_data,
                        source=VehicleInventoryEvent.Source.BACKOFFICE,
                    )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                if publish_to_telegram:
                    messages.success(
                        request,
                        f"تغییرات «{updated_machine.title}» در صف همگام‌سازی Telegram قرار گرفت.",
                    )
                else:
                    messages.success(
                        request,
                        f"اطلاعات ماشین «{updated_machine.title}» به‌روزرسانی شد.",
                    )
                return redirect("backoffice:machine_list")
    else:
        form = CarInventoryForm(instance=machine)

    return render(
        request,
        "backoffice/machines/form.html",
        {
            "form": form,
            "machine": machine,
            "form_title": "ویرایش اطلاعات ماشین",
            "submit_label": "ذخیرهٔ تغییرات",
            "notice": (
                "وضعیت فروش، کد رهگیری، مشتری و مرحلهٔ تحویل از این فرم تغییر "
                "نمی‌کنند؛ آن‌ها فقط با عملیات تخصصی خودشان مدیریت می‌شوند."
            ),
            "photo_preview": list(machine.photos.all()[:4]),
            "photo_count": machine.photos.count(),
            "can_publish_to_telegram": (
                request.user.has_perm("cars.publish_vehicle")
                and machine.status in {Car.Status.DRAFT, Car.Status.FOR_SALE}
            ),
        },
    )


@panel_permissions_required("cars.view_carphoto")
def machine_photo_manage(request, pk):
    machine = get_object_or_404(
        Car.objects.prefetch_related("photos", "videos"),
        pk=pk,
        is_deleted=False,
    )
    photos = list(machine.photos.all())
    photo_items = [
        {
            "photo": photo,
            "form": CarPhotoMetadataForm(
                instance=photo,
                prefix=f"photo-{photo.pk}",
            ),
        }
        for photo in photos
    ]
    can_modify_media = machine.status in INVENTORY_EDITABLE_STATUSES

    return render(
        request,
        "backoffice/machines/photos.html",
        {
            "machine": machine,
            "photo_items": photo_items,
            "upload_form": CarPhotoUploadForm(),
            "video_upload_form": CarVideoUploadForm(),
            "videos": list(machine.videos.all()),
            "can_modify_media": can_modify_media,
        },
    )


@panel_permissions_required("cars.add_carphoto")
@require_POST
def machine_photo_upload(request, pk):
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)
    form = CarPhotoUploadForm(request.POST, request.FILES)

    if form.is_valid():
        try:
            uploaded_photos = upload_car_photos(
                car_id=machine.id,
                actor=request.user,
                images=form.cleaned_data["images"],
                source=VehicleInventoryEvent.Source.BACKOFFICE,
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(
                request,
                f"{len(uploaded_photos)} تصویر برای ماشین «{machine.title}» افزوده شد.",
            )
    else:
        messages.error(
            request,
            " ".join(
                error for errors in form.errors.values() for error in errors
            ),
        )

    return redirect("backoffice:machine_photo_manage", pk=machine.pk)


@panel_permissions_required("cars.add_carvideo")
@require_POST
def machine_video_upload(request, pk):
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)
    form = CarVideoUploadForm(request.POST, request.FILES)

    if form.is_valid():
        try:
            video = upload_car_video(
                car_id=machine.id,
                actor=request.user,
                video_data=form.cleaned_data,
                source=VehicleInventoryEvent.Source.BACKOFFICE,
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"ویدیوی «{video.video.name}» افزوده شد.")
    else:
        messages.error(
            request,
            " ".join(error for errors in form.errors.values() for error in errors),
        )

    return redirect("backoffice:machine_photo_manage", pk=machine.pk)


@panel_permissions_required("cars.change_carphoto")
@require_POST
def machine_photo_update(request, pk, photo_pk):
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)
    photo = get_object_or_404(CarPhoto, pk=photo_pk, car=machine)
    form = CarPhotoMetadataForm(
        request.POST,
        instance=photo,
        prefix=f"photo-{photo.pk}",
    )

    if form.is_valid():
        try:
            update_car_photo_metadata(
                car_id=machine.id,
                photo_id=photo.id,
                actor=request.user,
                photo_data=form.cleaned_data,
                source=VehicleInventoryEvent.Source.BACKOFFICE,
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "اطلاعات تصویر به‌روزرسانی شد.")
    else:
        messages.error(
            request,
            " ".join(
                error for errors in form.errors.values() for error in errors
            ),
        )

    return redirect("backoffice:machine_photo_manage", pk=machine.pk)


@panel_permissions_required("cars.change_carphoto")
@require_POST
def machine_photo_set_cover(request, pk, photo_pk):
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)
    photo = get_object_or_404(CarPhoto, pk=photo_pk, car=machine)

    try:
        set_car_photo_cover(
            car_id=machine.id,
            photo_id=photo.id,
            actor=request.user,
            source=VehicleInventoryEvent.Source.BACKOFFICE,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "تصویر کاور ماشین تغییر کرد.")

    return redirect("backoffice:machine_photo_manage", pk=machine.pk)


@panel_permissions_required("cars.delete_carphoto")
@require_POST
def machine_photo_delete(request, pk, photo_pk):
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)
    photo = get_object_or_404(CarPhoto, pk=photo_pk, car=machine)

    try:
        delete_car_photo(
            car_id=machine.id,
            photo_id=photo.id,
            actor=request.user,
            source=VehicleInventoryEvent.Source.BACKOFFICE,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "تصویر ماشین حذف شد.")

    return redirect("backoffice:machine_photo_manage", pk=machine.pk)


@panel_permissions_required("cars.archive_vehicle")
def machine_archive(request, pk):
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)

    if request.method == "POST":
        form = VehicleArchiveReasonForm(request.POST)

        if form.is_valid():
            try:
                archive_vehicle(
                    car_id=machine.id,
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                    source=VehicleArchiveEvent.Source.ADMIN_DASHBOARD,
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"ماشین «{machine.title}» از فهرست فعال بایگانی شد.",
                )
                return redirect("backoffice:machine_list")
    else:
        form = VehicleArchiveReasonForm()

    return render(
        request,
        "backoffice/machines/archive_confirm.html",
        {
            "form": form,
            "machine": machine,
        },
    )


@panel_permissions_required("cars.publish_vehicle")
@require_POST
def machine_publish(request, pk):
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)

    try:
        publish_vehicle_for_sale(
            car_id=machine.id,
            actor=request.user,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, f"ماشین «{machine.title}» برای فروش منتشر شد.")

    return redirect("backoffice:machine_list")


@panel_permissions_required("cars.hold_vehicle")
def machine_hold_create(request, pk):
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)

    if request.method == "POST":
        form = VehicleHoldCreateForm(request.POST)

        if form.is_valid():
            try:
                place_vehicle_on_hold(
                    car_id=machine.id,
                    actor=request.user,
                    customer_name=form.cleaned_data["customer_name"],
                    customer_phone=form.cleaned_data["customer_phone"],
                    expires_at=form.cleaned_data["expires_at"],
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"برای ماشین «{machine.title}» رزرو موقت ثبت شد.",
                )
                return redirect("backoffice:vehicle_hold_list")
    else:
        form = VehicleHoldCreateForm()

    return render(
        request,
        "backoffice/machines/hold_form.html",
        {
            "form": form,
            "machine": machine,
        },
    )


@panel_permissions_required("cars.view_vehiclehold")
def vehicle_hold_list(request):
    hold_state = request.GET.get("state", "active")
    queryset = VehicleHold.objects.select_related(
        "car",
        "created_by",
        "released_by",
    ).order_by("-created_at")

    if hold_state == "released":
        queryset = queryset.filter(is_active=False)
    elif hold_state == "all":
        pass
    else:
        hold_state = "active"
        queryset = queryset.filter(is_active=True)

    context = _get_paginated_context(
        request=request,
        queryset=queryset,
        search_fields=(
            "car__title",
            "car__vehicle_code",
            "car__tracking_code",
            "customer_name",
            "customer_phone",
        ),
    )
    context.update(
        {
            "hold_state": hold_state,
            "now": timezone.now(),
        }
    )

    return render(request, "backoffice/machines/hold_list.html", context)


@panel_permissions_required("cars.release_vehicle_hold")
def vehicle_hold_release(request, pk):
    hold = get_object_or_404(
        VehicleHold.objects.select_related("car"),
        pk=pk,
    )

    if request.method == "POST":
        form = VehicleHoldReleaseForm(request.POST)

        if form.is_valid():
            try:
                release_vehicle_hold(
                    hold_id=hold.id,
                    actor=request.user,
                    release_note=form.cleaned_data["release_note"],
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"رزرو موقت ماشین «{hold.car.title}» آزاد شد.",
                )
                return redirect("backoffice:vehicle_hold_list")
    else:
        form = VehicleHoldReleaseForm()

    return render(
        request,
        "backoffice/machines/hold_release_confirm.html",
        {
            "form": form,
            "hold": hold,
        },
    )


@panel_permissions_required("cars.sell_vehicle")
def vehicle_hold_sale(request, pk):
    hold = get_object_or_404(
        VehicleHold.objects.select_related("car"),
        pk=pk,
        is_active=True,
    )

    if request.method == "POST":
        form = VehicleSaleForm(request.POST)

        if form.is_valid():
            try:
                sold_machine = mark_vehicle_as_sold(
                    car_id=hold.car_id,
                    actor=request.user,
                    full_name=form.cleaned_data["full_name"],
                    phone=form.cleaned_data["phone"],
                    telegram_id=form.cleaned_data["telegram_id"],
                    source=TrackingEvent.Source.ADMIN_DASHBOARD,
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    (
                        f"فروش ماشین «{sold_machine.title}» ثبت شد. "
                        f"کد رهگیری مشتری: {sold_machine.tracking_code}"
                    ),
                )
                return redirect("backoffice:pending_delivery_list")
    else:
        form = VehicleSaleForm(
            initial={
                "full_name": hold.customer_name,
                "phone": hold.customer_phone,
            }
        )

    return render(
        request,
        "backoffice/machines/sale_form.html",
        {
            "form": form,
            "hold": hold,
        },
    )


def _get_sold_machine_context(request, *, queryset):
    photo_queryset = (
        CarPhoto.objects.filter(image__isnull=False)
        .exclude(image="")
        .order_by("-is_cover", "sort_order", "pk")
    )
    context = _get_paginated_context(
        request=request,
        queryset=(
            queryset.select_related("customer", "current_stage")
            .prefetch_related(
                Prefetch(
                    "photos",
                    queryset=photo_queryset,
                    to_attr="delivery_list_photos",
                )
            )
            .order_by("-updated_at")
        ),
        search_fields=("customer__full_name", "vehicle_code", "tracking_code"),
    )

    for machine in context["page_obj"].object_list:
        machine.cover_photo = next(
            iter(getattr(machine, "delivery_list_photos", [])),
            None,
        )

    return context


@panel_permissions_required("cars.view_car")
def pending_delivery_list(request):
    context = _get_sold_machine_context(
        request,
        queryset=Car.objects.filter(
            is_deleted=False,
            status__in=[
                Car.Status.SOLD,
                Car.Status.IN_TRANSIT,
            ],
        ),
    )
    context.update(
        {
            "page_title": "ماشین‌های در انتظار تحویل",
            "page_description": (
                "فهرست ماشین‌های فروخته‌شده‌ای که هنوز تحویل نهایی نشده‌اند. "
                "جست‌وجو بر اساس نام خریدار یا کد رهگیری انجام می‌شود."
            ),
            "empty_message": "ماشین فروخته‌شده‌ای در انتظار تحویل وجود ندارد.",
            "is_delivered_list": False,
        }
    )
    return render(request, "backoffice/machines/sold_list.html", context)


@panel_permissions_required("cars.view_car")
def delivered_machine_list(request):
    context = _get_sold_machine_context(
        request,
        queryset=Car.objects.filter(
            is_deleted=False,
            status=Car.Status.DELIVERED,
        ),
    )
    context.update(
        {
            "page_title": "ماشین‌های تحویل‌داده‌شده",
            "page_description": (
                "ماشین‌هایی که آخرین مرحلهٔ فعال تحویل را کامل کرده‌اند. "
                "جست‌وجو بر اساس نام خریدار یا کد رهگیری انجام می‌شود."
            ),
            "empty_message": "هنوز ماشینی به‌عنوان تحویل‌داده‌شده ثبت نشده است.",
            "is_delivered_list": True,
        }
    )
    return render(request, "backoffice/machines/sold_list.html", context)


@panel_permissions_required("cars.view_car")
def delivery_machine_detail(request, pk):
    """Render the read-only operational dossier of one sold machine."""

    try:
        snapshot = get_delivery_machine_snapshot(car_id=pk)
    except Car.DoesNotExist as error:
        raise Http404("ماشین فروخته‌شده پیدا نشد.") from error

    car = snapshot["car"]
    list_url_name = (
        "backoffice:delivered_machine_list"
        if car.status == Car.Status.DELIVERED
        else "backoffice:pending_delivery_list"
    )

    reversal_allowed, reversal_rejection_reason = get_vehicle_sale_reversal_eligibility(
        car=car
    )
    can_reverse_sale = request.user.has_perm("cars.reverse_vehicle_sale") and reversal_allowed

    return render(
        request,
        "backoffice/machines/delivery_detail.html",
        {
            **snapshot,
            "page_title": f"پروندهٔ تحویل: {car.title}",
            "page_description": (
                "وضعیت عملیاتی، مسئولان مرحله، تاریخچهٔ مراحل و رویدادهای ثبت‌شدهٔ "
                "این ماشین در یک پرونده نمایش داده می‌شود."
            ),
            "list_url_name": list_url_name,
            "can_reverse_sale": can_reverse_sale,
            "can_sync_sale_telegram": request.user.has_perm("cars.sell_vehicle"),
            "sale_reversal_rejection_reason": reversal_rejection_reason,
        },
    )


@panel_permissions_required("cars.sell_vehicle")
@require_POST
def vehicle_sale_sync_telegram(request, pk):
    """One-time safe backfill for a previously sold vehicle channel post."""
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)
    if machine.status != Car.Status.SOLD:
        messages.error(request, "?????????? ???? ??? ???? ????? ?????????? ????? ??????.")
    else:
        outbox_message = queue_vehicle_channel_sale_state_change(
            car_id=machine.pk,
            actor=request.user,
        )
        if outbox_message is None:
            messages.info(request, "??? ??????????? ???? ??? ????? ?? ????? ???? ???? ???.")
        else:
            messages.success(request, "??????????? ??????????? ?? ?? Telegram ???? ????.")
    return redirect("backoffice:delivery_machine_detail", pk=machine.pk)


@panel_permissions_required("cars.reverse_vehicle_sale")
def vehicle_sale_reverse(request, pk):
    """Confirm a first-stage-only sale reversal through the shared service."""
    machine = get_object_or_404(Car, pk=pk, is_deleted=False)

    if request.method == "POST":
        form = VehicleSaleReversalForm(request.POST)
        if form.is_valid():
            try:
                reverse_vehicle_sale(
                    car_id=machine.pk,
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"???? ????? ?{machine.title}? ??? ?? ? ????? ?????? ?????? ???? ???.",
                )
                return redirect("backoffice:machine_list")
    else:
        form = VehicleSaleReversalForm()

    return render(
        request,
        "backoffice/machines/sale_reverse_confirm.html",
        {"form": form, "machine": machine},
    )


def _can_convert_custom_request(user):
    """Keep the panel's gate aligned with the shared conversion service."""

    return user.is_superuser or (
        user.has_perm("customers.convert_custom_vehicle_request_to_sale")
        and user.has_perm("cars.sell_vehicle")
    )


@panel_permissions_required("customers.view_customvehiclerequest")
def custom_vehicle_request_list(request):
    """List leads without inventing a parallel request lifecycle in the UI."""

    queryset = (
        CustomVehicleRequest.objects.select_related("sold_car", "sold_by")
        .annotate(read_receipt_count=Count("read_receipts", distinct=True))
        .order_by("-created_at")
    )
    context = _get_paginated_context(
        request=request,
        queryset=queryset,
        search_fields=(
            "full_name",
            "phone",
            "telegram_id",
            "preferred_brand",
            "preferred_model",
            "desired_vehicle_description",
        ),
    )
    context.update(
        {
            "page_title": "درخواست‌های خودروی سفارشی",
            "page_description": (
                "درخواست‌های مشتریانی که خودرو را در موجودی پیدا نکرده‌اند. "
                "بازکردن هر پرونده در تاریخچهٔ مشاهدهٔ کارکنان ثبت می‌شود."
            ),
        }
    )
    return render(request, "backoffice/custom_requests/list.html", context)


@panel_permissions_required("customers.view_customvehiclerequest")
def custom_vehicle_request_detail(request, pk):
    vehicle_request = get_object_or_404(
        CustomVehicleRequest.objects.select_related("sold_car", "sold_car__customer", "sold_by"),
        pk=pk,
    )

    # This is deliberately a service call: admin, panel, and future bot agents
    # get the same audit semantics rather than each writing a receipt directly.
    record_custom_vehicle_request_view(
        vehicle_request_id=vehicle_request.id,
        employee=request.user,
    )
    read_receipts = CustomVehicleRequestReadReceipt.objects.filter(
        vehicle_request=vehicle_request
    ).select_related("employee").order_by("first_seen_at")

    return render(
        request,
        "backoffice/custom_requests/detail.html",
        {
            "vehicle_request": vehicle_request,
            "read_receipts": read_receipts,
            "can_convert": vehicle_request.status == CustomVehicleRequest.Status.NEW
            and _can_convert_custom_request(request.user),
        },
    )


@panel_permissions_required("customers.view_customvehiclerequest")
def custom_vehicle_request_convert(request, pk):
    """Convert a lead through the existing sale service, never by model writes."""

    if not _can_convert_custom_request(request.user):
        raise PermissionDenied

    vehicle_request = get_object_or_404(CustomVehicleRequest, pk=pk)
    record_custom_vehicle_request_view(
        vehicle_request_id=vehicle_request.id,
        employee=request.user,
    )

    if vehicle_request.status != CustomVehicleRequest.Status.NEW:
        messages.info(request, "این درخواست قبلاً به فروش تبدیل شده است.")
        return redirect("backoffice:custom_vehicle_request_detail", pk=vehicle_request.pk)

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
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"فروش ثبت شد؛ کد رهگیری خودرو: {sold_car.tracking_code}",
                )
                return redirect("backoffice:delivery_machine_detail", pk=sold_car.pk)
    else:
        form = AdminCustomVehicleRequestConversionForm(
            initial={"telegram_id": vehicle_request.telegram_id}
        )

    return render(
        request,
        "backoffice/custom_requests/convert.html",
        {"vehicle_request": vehicle_request, "form": form},
    )


@panel_permissions_required("customers.view_customer")
def customer_list(request):
    queryset = Customer.objects.annotate(car_count=Count("cars", distinct=True)).order_by(
        "full_name", "pk"
    )
    context = _get_paginated_context(
        request=request,
        queryset=queryset,
        search_fields=("full_name", "phone", "telegram_id", "cars__vehicle_code", "cars__tracking_code"),
    )
    context.update(
        {
            "page_title": "مشتریان",
            "page_description": (
                "پرونده‌های مشتریانِ فروش‌نهایی‌شده؛ جست‌وجو با نام، تلفن، شناسهٔ تلگرام یا کد رهگیری."
            ),
        }
    )
    return render(request, "backoffice/customers/list.html", context)


@panel_permissions_required("customers.view_customer")
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    sold_cars = customer.cars.select_related("current_stage").order_by("-updated_at")
    return render(
        request,
        "backoffice/customers/detail.html",
        {"customer": customer, "sold_cars": sold_cars},
    )


@panel_permissions_required("tracking.confirm_tracking_stage")
def clearance_operation(request):
    """Two-step, code-based stage operation for staff and System Administrators."""

    recent_events = (
        TrackingEvent.objects.filter(performed_by=request.user)
        .select_related("car", "new_stage")
        .order_by("-created_at")[:8]
    )

    if request.method == "POST" and "confirm_operation" in request.POST:
        confirmation_form = ClearanceConfirmationForm(request.POST)
        if confirmation_form.is_valid():
            tracking_code = confirmation_form.cleaned_data["tracking_code"]
            operation = confirmation_form.cleaned_data["operation"]
            try:
                if operation == ClearanceTrackingCodeForm.Operation.ENTER:
                    preview = get_stage_confirmation_preview(
                        tracking_code=tracking_code,
                        staff=request.user,
                    )
                    confirm_stage(
                        car=preview["car"],
                        stage=preview["stage"],
                        staff=request.user,
                    )
                    success_message = f"ورود «{preview['car'].title}» به مرحلهٔ «{preview['stage'].name}» ثبت شد."
                else:
                    preview = get_stage_completion_preview(
                        tracking_code=tracking_code,
                        staff=request.user,
                    )
                    complete_stage(
                        car=preview["car"],
                        stage=preview["stage"],
                        staff=request.user,
                    )
                    success_message = f"مرحلهٔ «{preview['stage'].name}» برای «{preview['car'].title}» تکمیل شد."
            except ValidationError as error:
                _add_service_errors(confirmation_form, error)
            else:
                messages.success(request, success_message)
                return redirect("backoffice:clearance_operation")

            return render(
                request,
                "backoffice/clearance/confirm.html",
                {
                    "form": confirmation_form,
                    "preview": preview if "preview" in locals() else None,
                    "recent_events": recent_events,
                },
            )
    elif request.method == "POST":
        lookup_form = ClearanceTrackingCodeForm(request.POST)
        if lookup_form.is_valid():
            tracking_code = lookup_form.cleaned_data["tracking_code"]
            operation = lookup_form.cleaned_data["operation"]
            try:
                preview = (
                    get_stage_confirmation_preview(
                        tracking_code=tracking_code,
                        staff=request.user,
                    )
                    if operation == ClearanceTrackingCodeForm.Operation.ENTER
                    else get_stage_completion_preview(
                        tracking_code=tracking_code,
                        staff=request.user,
                    )
                )
            except ValidationError as error:
                _add_service_errors(lookup_form, error)
            else:
                confirmation_form = ClearanceConfirmationForm(
                    initial={"tracking_code": tracking_code, "operation": operation}
                )
                return render(
                    request,
                    "backoffice/clearance/confirm.html",
                    {
                        "form": confirmation_form,
                        "preview": preview,
                        "operation": operation,
                        "recent_events": recent_events,
                    },
                )
    else:
        lookup_form = ClearanceTrackingCodeForm()

    return render(
        request,
        "backoffice/clearance/operation.html",
        {"form": lookup_form, "recent_events": recent_events},
    )


@panel_permissions_required("tracking.confirm_tracking_stage")
def clearance_queue(request):
    """Permission-scoped operational queue for the logged-in clearance user."""

    queue = get_clearance_work_queue(staff=request.user)
    query = (request.GET.get("q") or "").strip().casefold()
    action_filter = request.GET.get("action", "all")
    if action_filter not in {"all", "receive", "complete", "completed"}:
        action_filter = "all"

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if action_filter == "completed":
        history = get_completed_clearance_history(staff=request.user)
        try:
            if date_from:
                history = history.filter(completed_at__date__gte=date.fromisoformat(date_from))
            if date_to:
                history = history.filter(completed_at__date__lte=date.fromisoformat(date_to))
        except ValueError:
            messages.error(request, "فرمت تاریخ برای جست‌وجو معتبر نیست.")

        queue = [
            {
                "car": progress.car,
                "stage": progress.stage,
                "action": "completed",
                "progress": progress,
            }
            for progress in history
        ]

    if query:
        queue = [
            item for item in queue
            if query in " ".join(
                filter(
                    None,
                    (
                        item["car"].title,
                        item["car"].tracking_code,
                        item["car"].customer.full_name if item["car"].customer else "",
                        item["stage"].name,
                    ),
                ),
            ).casefold()
        ]
    if action_filter not in {"all", "completed"}:
        queue = [item for item in queue if item["action"] == action_filter]

    paginator = Paginator(queue, _get_requested_per_page(request, default=20))
    return render(
        request,
        "backoffice/clearance/queue.html",
        {
            "page_obj": paginator.get_page(request.GET.get("page")),
            "query": request.GET.get("q", "").strip(),
            "result_count": paginator.count,
            "action_filter": action_filter,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


def _get_queue_item_or_error(*, staff, car_pk, action):
    for item in get_clearance_work_queue(staff=staff):
        if item["car"].pk == car_pk and item["action"] == action:
            return item
    raise ValidationError("این خودرو دیگر در صف عملیاتی مجاز شما قرار ندارد.")


@require_POST
@panel_permissions_required("tracking.confirm_tracking_stage")
def clearance_queue_receive(request, pk):
    try:
        item = _get_queue_item_or_error(
            staff=request.user, car_pk=pk, action="receive",
        )
        preview = get_stage_confirmation_preview(
            tracking_code=item["car"].tracking_code,
            staff=request.user,
        )
        confirm_stage(
            car=preview["car"],
            stage=preview["stage"],
            staff=request.user,
            source=TrackingEvent.Source.ADMIN_DASHBOARD,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(
            request,
            f"خودرو «{item['car'].title}» در مرحلهٔ «{item['stage'].name}» تحویل گرفته شد.",
        )
    return redirect("backoffice:clearance_queue")


@require_POST
@panel_permissions_required("tracking.confirm_tracking_stage")
def clearance_queue_complete(request, pk):
    try:
        item = _get_queue_item_or_error(
            staff=request.user, car_pk=pk, action="complete",
        )
        preview = get_stage_completion_preview(
            tracking_code=item["car"].tracking_code,
            staff=request.user,
        )
        complete_stage(
            car=preview["car"],
            stage=preview["stage"],
            staff=request.user,
            source=TrackingEvent.Source.ADMIN_DASHBOARD,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(
            request,
            f"ترخیص مرحلهٔ «{item['stage'].name}» برای خودرو «{item['car'].title}» ثبت شد.",
        )
    return redirect("backoffice:clearance_queue")


def _tracking_import_queryset_for(request):
    queryset = TrackingImportJob.objects.select_related("requested_by")
    return queryset if request.user.is_superuser else queryset.filter(requested_by=request.user)


@panel_permissions_required("tracking.import_tracking_stage_updates")
def tracking_import_list(request):
    queryset = _tracking_import_queryset_for(request)
    status_filter = request.GET.get("status", "all")
    if status_filter in TrackingImportJob.Status.values:
        queryset = queryset.filter(status=status_filter)
    else:
        status_filter = "all"

    context = _get_paginated_context(
        request=request,
        queryset=queryset.order_by("-created_at", "-pk"),
        search_fields=("original_filename", "requested_by__username"),
    )
    context.update(
        {
            "status_filter": status_filter,
            "status_choices": TrackingImportJob.Status.choices,
        }
    )
    return render(request, "backoffice/imports/list.html", context)


@panel_permissions_required("tracking.import_tracking_stage_updates")
def tracking_import_create(request):
    if request.method == "POST":
        form = TrackingImportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                job = create_tracking_import_job(
                    spreadsheet=form.cleaned_data["spreadsheet"],
                    actor=request.user,
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    "فایل دریافت شد و برای پردازش پس‌زمینه در صف قرار گرفت.",
                )
                return redirect("backoffice:tracking_import_detail", pk=job.pk)
    else:
        form = TrackingImportUploadForm()

    return render(request, "backoffice/imports/create.html", {"form": form})


@panel_permissions_required("tracking.import_tracking_stage_updates")
def tracking_import_detail(request, pk):
    job = get_object_or_404(_tracking_import_queryset_for(request), pk=pk)
    row_queryset = job.rows.order_by("row_number", "pk")
    row_context = _get_paginated_context(
        request=request,
        queryset=row_queryset,
        search_fields=("tracking_code", "stage_name", "message"),
        per_page=50,
    )
    return render(
        request,
        "backoffice/imports/detail.html",
        {"job": job, **row_context},
    )


@panel_permissions_required("blog.add_post")
def blog_post_create(request):
    if request.method == "POST":
        form = BlogPostForm(request.POST, request.FILES)

        if form.is_valid():
            try:
                post = create_post(
                    actor=request.user,
                    post_data=form.cleaned_data,
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"مقالهٔ «{post.title}» به‌صورت پیش‌نویس ذخیره شد.",
                )
                if request.user.is_superuser or request.user.has_perm(
                    "blog.change_post"
                ):
                    return redirect("backoffice:blog_post_edit", pk=post.pk)
                return redirect("backoffice:blog_post_list")
    else:
        form = BlogPostForm()

    return render(
        request,
        "backoffice/blog/form.html",
        {
            "form": form,
            "post": None,
            "form_title": "افزودن مقاله",
            "submit_label": "ذخیرهٔ پیش‌نویس",
            "notice": (
                "مقاله ابتدا فقط به‌صورت پیش‌نویس ذخیره می‌شود. انتشار عمومی "
                "یک عملیات جداگانه و قابل‌کنترل است."
            ),
        },
    )


@panel_permissions_required("blog.view_post")
def blog_post_list(request):
    status_filter = request.GET.get("status", "all")
    queryset = Post.objects.select_related("author", "category").order_by(
        "-updated_at",
        "-pk",
    )

    if status_filter in {Post.Status.DRAFT, Post.Status.PUBLISHED}:
        queryset = queryset.filter(status=status_filter)
    else:
        status_filter = "all"

    context = _get_paginated_context(
        request=request,
        queryset=queryset,
        search_fields=("title",),
    )
    context.update({"status_filter": status_filter})

    return render(request, "backoffice/blog/list.html", context)


@panel_permissions_required("blog.change_post")
def blog_post_edit(request, pk):
    post = get_object_or_404(Post.objects.select_related("author", "category"), pk=pk)

    if request.method == "POST":
        form = BlogPostForm(request.POST, request.FILES, instance=post)

        if form.is_valid():
            try:
                post = update_post(
                    post_id=post.pk,
                    actor=request.user,
                    post_data=form.cleaned_data,
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(request, f"مقالهٔ «{post.title}» به‌روزرسانی شد.")
                return redirect("backoffice:blog_post_edit", pk=post.pk)
    else:
        form = BlogPostForm(instance=post)

    return render(
        request,
        "backoffice/blog/form.html",
        {
            "form": form,
            "post": post,
            "form_title": "ویرایش مقاله",
            "submit_label": "ذخیرهٔ تغییرات",
            "notice": (
                "تغییرات محتوا و SEO در این فرم ذخیره می‌شوند. وضعیت انتشار فقط با "
                "دکمهٔ اختصاصی انتشار یا بازگرداندن به پیش‌نویس تغییر می‌کند."
            ),
        },
    )


@panel_permissions_required("blog.change_post", "blog.publish_post")
@require_POST
def blog_post_publish(request, pk):
    post = get_object_or_404(Post, pk=pk)

    try:
        publish_post(post_id=post.pk, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, f"مقالهٔ «{post.title}» در سایت منتشر شد.")

    return redirect("backoffice:blog_post_list")


@panel_permissions_required("blog.change_post", "blog.publish_post")
@require_POST
def blog_post_unpublish(request, pk):
    post = get_object_or_404(Post, pk=pk)

    try:
        unpublish_post(post_id=post.pk, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, f"مقالهٔ «{post.title}» به پیش‌نویس بازگردانده شد.")

    return redirect("backoffice:blog_post_list")


@panel_permissions_required("blog.delete_post")
def blog_post_delete(request, pk):
    post = get_object_or_404(Post.objects.select_related("author", "category"), pk=pk)

    if request.method == "POST":
        try:
            delete_post(post_id=post.pk, actor=request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"مقالهٔ «{post.title}» حذف شد.")
            return redirect("backoffice:blog_post_list")

    return render(request, "backoffice/blog/delete_confirm.html", {"post": post})


@panel_permissions_required(
    "core.manage_site_identity",
    "core.manage_site_content",
    "core.manage_site_seo",
    "core.manage_site_navigation",
    "core.manage_site_footer",
    "core.manage_site_social_links",
    "core.manage_static_pages",
)
def site_settings(request):
    site_config = SiteConfiguration.get_solo()
    seo_config, _ = SeoConfiguration.objects.get_or_create(
        site_configuration=site_config,
    )
    home_config, _ = HomePageConfiguration.objects.get_or_create(
        site_configuration=site_config,
    )
    user = request.user
    cards = (
        {
            "title": "هویت برند و SEO",
            "description": "نام، لوگو، رنگ‌ها، راه‌های ارتباطی و تنظیمات موتورهای جست‌وجو.",
            "icon": "fa-diamond",
            "url_name": "backoffice:site_identity_settings",
            "permission": "core.manage_site_identity",
            "secondary_permission": "core.manage_site_seo",
            "count": "تنظیمات اصلی",
        },
        {
            "title": "محتوای صفحهٔ اصلی",
            "description": "Hero، تصویرها، خودرو ویژه، CTA، مسیر واردات و بخش رهگیری.",
            "icon": "fa-home",
            "url_name": "backoffice:site_homepage_settings",
            "permission": "core.manage_site_content",
            "count": "صفحهٔ اول",
        },
        {
            "title": "منوی Header",
            "description": "پیوندهای ناوبری بالای سایت، ترتیب و وضعیت نمایش آن‌ها.",
            "icon": "fa-bars",
            "url_name": "backoffice:site_collection_list",
            "url_kwargs": {"collection": "header"},
            "permission": "core.manage_site_navigation",
            "count": HeaderNavigationItem.objects.count(),
        },
        {
            "title": "Footer و لینک‌ها",
            "description": "ستون‌های فوتر، پیوندهای هر ستون و ترتیب نمایش در سایت.",
            "icon": "fa-columns",
            "url_name": "backoffice:site_collection_list",
            "url_kwargs": {"collection": "footer_sections"},
            "permission": "core.manage_site_footer",
            "count": FooterSection.objects.count(),
        },
        {
            "title": "شبکه‌های اجتماعی",
            "description": "Telegram، Instagram، WhatsApp و سایر لینک‌های رسمی برند.",
            "icon": "fa-share-alt",
            "url_name": "backoffice:site_collection_list",
            "url_kwargs": {"collection": "social"},
            "permission": "core.manage_site_social_links",
            "count": SocialLink.objects.count(),
        },
        {
            "title": "کارت‌ها و دسترسی‌های سریع",
            "description": "کارت‌های معرفی و کلیدهای کنترل‌شدهٔ صفحهٔ اول.",
            "icon": "fa-th-large",
            "url_name": "backoffice:site_collection_list",
            "url_kwargs": {"collection": "home_cards"},
            "permission": "core.manage_site_content",
            "count": HomeFeatureCard.objects.filter(home_page=home_config).count(),
        },
        {
            "title": "صفحات ثابت",
            "description": "صفحات قابل انتشار با عنوان، متن، URL و SEO مستقل.",
            "icon": "fa-file-text-o",
            "url_name": "backoffice:site_collection_list",
            "url_kwargs": {"collection": "pages"},
            "permission": "core.manage_static_pages",
            "count": StaticPage.objects.count(),
        },
    )
    for card in cards:
        card["allowed"] = user.is_superuser or user.has_perm(card["permission"])
        if card.get("secondary_permission"):
            card["allowed"] = card["allowed"] and (
                user.is_superuser or user.has_perm(card["secondary_permission"])
            )
    return render(
        request,
        "backoffice/settings/dashboard.html",
        {"cards": cards, "site_config": site_config},
    )


def _require_site_permission(request, permission):
    if not (request.user.is_superuser or request.user.has_perm(permission)):
        raise PermissionDenied


@staff_member_required
def site_identity_settings(request):
    _require_site_permission(request, "core.manage_site_identity")
    _require_site_permission(request, "core.manage_site_seo")
    configuration = SiteConfiguration.get_solo()
    seo_configuration, _ = SeoConfiguration.objects.get_or_create(
        site_configuration=configuration,
    )
    if request.method == "POST":
        identity_form = SiteIdentityForm(
            request.POST, request.FILES, instance=configuration,
        )
        seo_form = SeoConfigurationForm(
            request.POST, request.FILES, instance=seo_configuration,
        )
        if identity_form.is_valid() and seo_form.is_valid():
            try:
                update_site_identity_and_seo(
                    identity_form=identity_form,
                    seo_form=seo_form,
                    actor=request.user,
                )
            except ValidationError as error:
                identity_form.add_error(None, error)
            else:
                messages.success(request, "هویت برند و تنظیمات SEO با موفقیت ذخیره شد.")
                return redirect("backoffice:site_identity_settings")
    else:
        identity_form = SiteIdentityForm(instance=configuration)
        seo_form = SeoConfigurationForm(instance=seo_configuration)
    return render(
        request,
        "backoffice/settings/identity.html",
        {"identity_form": identity_form, "seo_form": seo_form},
    )


@staff_member_required
def site_homepage_settings(request):
    _require_site_permission(request, "core.manage_site_content")
    configuration = SiteConfiguration.get_solo()
    home_configuration, _ = HomePageConfiguration.objects.get_or_create(
        site_configuration=configuration,
    )
    if request.method == "POST":
        form = HomePageConfigurationForm(
            request.POST, request.FILES, instance=home_configuration,
        )
        if form.is_valid():
            try:
                update_home_page_configuration(form=form, actor=request.user)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, "محتوای صفحهٔ اصلی ذخیره شد.")
                return redirect("backoffice:site_homepage_settings")
    else:
        form = HomePageConfigurationForm(instance=home_configuration)
    return render(request, "backoffice/settings/homepage.html", {"form": form})


SITE_COLLECTIONS = {
    "header": {
        "model": HeaderNavigationItem, "form": HeaderNavigationItemForm,
        "permission": "core.manage_site_navigation", "title": "منوی Header",
        "description": "پیوندهای بالای سایت را با ترتیب و دسترسی‌پذیری کنترل کنید.",
    },
    "footer_sections": {
        "model": FooterSection, "form": FooterSectionForm,
        "permission": "core.manage_site_footer", "title": "ستون‌های Footer",
        "description": "ابتدا ستون‌ها را تعریف کنید؛ سپس لینک‌های هر ستون را بسازید.",
    },
    "footer_links": {
        "model": FooterLink, "form": FooterLinkForm,
        "permission": "core.manage_site_footer", "title": "لینک‌های Footer",
        "description": "هر لینک را به ستون موردنظر، مسیر امن و ترتیب نمایش وصل کنید.",
    },
    "social": {
        "model": SocialLink, "form": SocialLinkForm,
        "permission": "core.manage_site_social_links", "title": "شبکه‌های اجتماعی",
        "description": "فقط لینک‌های رسمی و تأییدشدهٔ برند را منتشر کنید.",
    },
    "home_cards": {
        "model": HomeFeatureCard, "form": HomeFeatureCardForm,
        "permission": "core.manage_site_content", "title": "کارت‌های صفحهٔ اصلی",
        "description": "پیام‌های اعتمادساز و فراخوان‌های صفحهٔ اصلی.", "home_page_owned": True,
    },
    "quick_actions": {
        "model": HomeQuickAction, "form": HomeQuickActionForm,
        "permission": "core.manage_site_content", "title": "دسترسی‌های سریع صفحهٔ اصلی",
        "description": "دکمه‌های کنترل‌شدهٔ Hero؛ نوع هر دکمه یکتا است.", "home_page_owned": True,
    },
    "pages": {
        "model": StaticPage, "form": StaticPageForm,
        "permission": "core.manage_static_pages", "title": "صفحات ثابت",
        "description": "صفحهٔ قابل انتشار با URL و تنظیمات SEO مستقل.",
    },
}


def _get_site_collection_or_404(collection):
    try:
        return SITE_COLLECTIONS[collection]
    except KeyError as error:
        raise Http404("Unknown settings collection") from error


@staff_member_required
def site_collection_list(request, collection):
    config = _get_site_collection_or_404(collection)
    _require_site_permission(request, config["permission"])
    queryset = config["model"].objects.all()
    if config.get("home_page_owned"):
        queryset = queryset.select_related("home_page")
    return render(
        request,
        "backoffice/settings/collection_list.html",
        {"collection": collection, "config": config, "items": queryset},
    )


@staff_member_required
def site_collection_create(request, collection):
    config = _get_site_collection_or_404(collection)
    _require_site_permission(request, config["permission"])
    form_class = config["form"]
    if request.method == "POST":
        form = form_class(request.POST, request.FILES)
        if form.is_valid():
            try:
                create_site_collection_item(
                    form=form, actor=request.user, permission=config["permission"],
                    home_page_owned=config.get("home_page_owned", False),
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, "آیتم جدید با موفقیت ایجاد شد.")
                return redirect("backoffice:site_collection_list", collection=collection)
    else:
        form = form_class()
    return render(request, "backoffice/settings/collection_form.html", {"collection": collection, "config": config, "form": form, "object": None})


@staff_member_required
def site_collection_edit(request, collection, pk):
    config = _get_site_collection_or_404(collection)
    _require_site_permission(request, config["permission"])
    instance = get_object_or_404(config["model"], pk=pk)
    form_class = config["form"]
    if request.method == "POST":
        form = form_class(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            try:
                update_site_collection_item(
                    form=form, actor=request.user, permission=config["permission"],
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, "تغییرات آیتم ذخیره شد.")
                return redirect("backoffice:site_collection_list", collection=collection)
    else:
        form = form_class(instance=instance)
    return render(request, "backoffice/settings/collection_form.html", {"collection": collection, "config": config, "form": form, "object": instance})


@staff_member_required
def site_collection_delete(request, collection, pk):
    config = _get_site_collection_or_404(collection)
    _require_site_permission(request, config["permission"])
    instance = get_object_or_404(config["model"], pk=pk)
    if request.method == "POST":
        try:
            delete_site_collection_item(
                instance=instance, actor=request.user, permission=config["permission"],
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "آیتم حذف شد.")
            return redirect("backoffice:site_collection_list", collection=collection)
    return render(request, "backoffice/settings/collection_delete.html", {"collection": collection, "config": config, "object": instance})


@system_administrator_required
def stage_configuration(request):
    """Compatibility route for the original single delivery-stage menu item."""

    return redirect("backoffice:stage_list")


def _get_previous_active_stage(stage):
    return (
        Stage.objects.filter(
            is_active=True,
            order__lt=stage.order,
        )
        .order_by("-order", "-pk")
        .first()
    )


def _get_stage_configuration_lists():
    """Prepare display-only stage data without allowing direct mutation."""

    in_flight_filter = Q(
        progress_records__car__is_deleted=False,
        progress_records__car__status__in=[Car.Status.SOLD, Car.Status.IN_TRANSIT],
    )
    entered_filter = (
        in_flight_filter
        & Q(progress_records__actual_arrival__isnull=False)
        & Q(progress_records__completed_at__isnull=True)
        & Q(progress_records__skipped_at__isnull=True)
    )
    current_car_filter = Q(
        cars_at_stage__is_deleted=False,
        cars_at_stage__status__in=[Car.Status.SOLD, Car.Status.IN_TRANSIT],
    )
    stage_queryset = (
        Stage.objects.prefetch_related("staff_members__user")
        .annotate(
            current_vehicle_count=Count(
                "cars_at_stage",
                filter=current_car_filter,
                distinct=True,
            ),
            entered_vehicle_count=Count(
                "progress_records",
                filter=entered_filter,
                distinct=True,
            ),
        )
        .order_by("order", "pk")
    )
    active_stages = list(stage_queryset.filter(is_active=True))
    archived_stages = list(stage_queryset.filter(is_active=False))
    transition_map = {
        (transition.from_stage_id, transition.to_stage_id): transition
        for transition in StageTransition.objects.filter(
            is_active=True,
            from_stage__in=active_stages,
            to_stage__in=active_stages,
        )
    }

    for index, stage in enumerate(active_stages):
        stage.previous_active_stage = active_stages[index - 1] if index else None
        stage.next_active_stage = (
            active_stages[index + 1]
            if index + 1 < len(active_stages)
            else None
        )
        stage.incoming_transition = (
            transition_map.get(
                (stage.previous_active_stage.pk, stage.pk)
            )
            if stage.previous_active_stage
            else None
        )
        stage.outgoing_transition = (
            transition_map.get((stage.pk, stage.next_active_stage.pk))
            if stage.next_active_stage
            else None
        )
        stage.can_archive = bool(
            stage.previous_active_stage and stage.next_active_stage
        )

    return (
        active_stages,
        archived_stages,
        get_linear_stage_route_integrity(),
    )


@system_administrator_required
def stage_list(request):
    active_stages, archived_stages, route_integrity = _get_stage_configuration_lists()

    return render(
        request,
        "backoffice/stages/list.html",
        {
            "active_stages": active_stages,
            "archived_stages": archived_stages,
            "active_stage_count": len(active_stages),
            "route_integrity": route_integrity,
        },
    )


@system_administrator_required
def stage_transition_repair(request):
    """Preview and repair the active linear route without using Django Admin."""

    route_integrity = get_linear_stage_route_integrity()

    if len(route_integrity["stages"]) < 2:
        messages.info(
            request,
            "برای تعریف Transition دست‌کم دو مرحلهٔ فعال لازم است.",
        )
        return redirect("backoffice:stage_list")

    if request.method == "POST":
        form = TransitionRepairForm(
            request.POST,
            route_integrity=route_integrity,
        )

        if form.is_valid():
            try:
                result = repair_linear_stage_transitions(
                    actor=request.user,
                    transition_durations=form.get_transition_durations(),
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    "مسیر خطی تحویل با موفقیت ترمیم شد: "
                    f"{result['created_count']} Transition جدید، "
                    f"{result['reactivated_count']} Transition فعال‌شده و "
                    f"{result['deactivated_count']} Transition غیرخطی غیرفعال شد. "
                    f"ETA {result['replanned_vehicle_count']} ماشین در حال تحویل به‌روزرسانی شد.",
                )
                return redirect("backoffice:stage_list")
    else:
        form = TransitionRepairForm(route_integrity=route_integrity)

    return render(
        request,
        "backoffice/stages/transition_repair.html",
        {
            "form": form,
            "route_integrity": route_integrity,
        },
    )


@system_administrator_required
def stage_create(request):
    route_integrity = get_linear_stage_route_integrity()
    if not route_integrity["is_valid"]:
        messages.warning(
            request,
            "پیش از تعریف مرحلهٔ جدید، ابتدا مسیر و Transitionهای فعلی را ترمیم کنید.",
        )
        return redirect("backoffice:stage_transition_repair")

    previous_stage = (
        Stage.objects.filter(is_active=True).order_by("-order", "-pk").first()
    )

    if request.method == "POST":
        form = StageDefinitionForm(
            request.POST,
            previous_stage=previous_stage,
        )

        if form.is_valid():
            try:
                stage = create_linear_stage(
                    actor=request.user,
                    name=form.cleaned_data["name"],
                    duration_from_previous=form.cleaned_data[
                        "duration_from_previous"
                    ],
                    assigned_staff=form.cleaned_data["assigned_staff"],
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"مرحلهٔ «{stage.name}» با موفقیت به انتهای مسیر تحویل افزوده شد.",
                )
                return redirect("backoffice:stage_list")
    else:
        form = StageDefinitionForm(previous_stage=previous_stage)

    return render(
        request,
        "backoffice/stages/form.html",
        {
            "form": form,
            "form_title": "تعریف مرحلهٔ تحویل",
            "submit_label": "افزودن مرحله",
            "previous_stage": previous_stage,
            "notice": (
                "مرحلهٔ جدید به انتهای مسیر خطی اضافه می‌شود. برای همهٔ ماشین‌های "
                "در حال تحویل، رکورد مرحله و ETA آینده به‌صورت امن و مشترک به‌روزرسانی می‌شود."
            ),
        },
    )


@system_administrator_required
def stage_edit(request, pk):
    route_integrity = get_linear_stage_route_integrity()
    if not route_integrity["is_valid"]:
        messages.warning(
            request,
            "برای ویرایش مرحله، ابتدا مسیر و Transitionهای فعلی را از همین پنل ترمیم کنید.",
        )
        return redirect("backoffice:stage_transition_repair")

    stage = get_object_or_404(Stage, pk=pk, is_active=True)
    previous_stage = _get_previous_active_stage(stage)
    incoming_transition = (
        StageTransition.objects.filter(
            from_stage=previous_stage,
            to_stage=stage,
            is_active=True,
        ).first()
        if previous_stage
        else None
    )
    initial = {}

    if incoming_transition is not None:
        initial["duration_from_previous"] = (
            incoming_transition.estimated_duration_days
        )

    if request.method == "POST":
        form = StageDefinitionForm(
            request.POST,
            stage=stage,
            previous_stage=previous_stage,
            initial=initial,
        )

        if form.is_valid():
            try:
                stage = update_linear_stage(
                    stage=stage,
                    actor=request.user,
                    name=form.cleaned_data["name"],
                    duration_from_previous=form.cleaned_data[
                        "duration_from_previous"
                    ],
                    assigned_staff=form.cleaned_data["assigned_staff"],
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(request, f"مرحلهٔ «{stage.name}» به‌روزرسانی شد.")
                return redirect("backoffice:stage_list")
    else:
        form = StageDefinitionForm(
            stage=stage,
            previous_stage=previous_stage,
            initial=initial,
        )

    return render(
        request,
        "backoffice/stages/form.html",
        {
            "form": form,
            "stage": stage,
            "previous_stage": previous_stage,
            "form_title": f"ویرایش مرحلهٔ «{stage.name}»",
            "submit_label": "ذخیرهٔ تغییرات",
            "notice": (
                "نام مرحله، مسئولان آن و زمان انتقال از مرحلهٔ قبلی در این صفحه "
                "مدیریت می‌شود. تغییر زمان، ETA ماشین‌های در انتظار تحویل را پویا تغییر می‌دهد."
            ),
        },
    )


@system_administrator_required
def stage_archive(request, pk):
    route_integrity = get_linear_stage_route_integrity()
    if not route_integrity["is_valid"]:
        messages.warning(
            request,
            "برای بایگانی مرحله، ابتدا مسیر و Transitionهای فعلی را از همین پنل ترمیم کنید.",
        )
        return redirect("backoffice:stage_transition_repair")

    stage = get_object_or_404(Stage, pk=pk, is_active=True)
    impact = get_stage_archive_impact(stage=stage)
    previous_stage = _get_previous_active_stage(stage)
    next_stage = (
        Stage.objects.filter(is_active=True, order__gt=stage.order)
        .order_by("order", "pk")
        .first()
    )
    initial = {}

    if previous_stage and next_stage:
        incoming_transition = StageTransition.objects.filter(
            from_stage=previous_stage,
            to_stage=stage,
            is_active=True,
        ).first()
        outgoing_transition = StageTransition.objects.filter(
            from_stage=stage,
            to_stage=next_stage,
            is_active=True,
        ).first()

        if incoming_transition and outgoing_transition:
            initial["replacement_duration_days"] = (
                incoming_transition.estimated_duration_days
                + outgoing_transition.estimated_duration_days
            )

    if request.method == "POST":
        form = StageArchiveForm(request.POST, initial=initial)

        if form.is_valid():
            try:
                archive_stage(
                    stage=stage,
                    actor=request.user,
                    replacement_duration_days=form.cleaned_data[
                        "replacement_duration_days"
                    ],
                    note=form.cleaned_data["note"],
                    confirm_affected_vehicles=form.cleaned_data[
                        "confirm_affected_vehicles"
                    ],
                    source=TrackingEvent.Source.ADMIN_DASHBOARD,
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"مرحلهٔ «{stage.name}» بایگانی شد و مسیر جایگزین اعمال شد.",
                )
                return redirect("backoffice:stage_list")
    else:
        form = StageArchiveForm(initial=initial)

    return render(
        request,
        "backoffice/stages/archive_confirm.html",
        {
            "form": form,
            "stage": stage,
            "impact": impact,
            "previous_stage": previous_stage,
            "next_stage": next_stage,
        },
    )


# ---------------------------------------------------------------------------
# Staff management
# ---------------------------------------------------------------------------


def _internal_staff_queryset():
    """Shared optimized queryset for the staff directory and profile pages."""

    user_model = get_user_model()
    now = timezone.now()
    active_link_query = TelegramStaffLink.objects.filter(
        user_id=OuterRef("pk"),
        is_active=True,
    )
    pending_link_code_query = TelegramStaffLinkToken.objects.filter(
        user_id=OuterRef("pk"),
        used_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=now,
    )

    return (
        user_model.objects.filter(is_staff=True)
        .select_related("staff_profile")
        .prefetch_related(
            "groups",
            "user_permissions__content_type",
            "staff_profile__assigned_stages",
            Prefetch(
                "telegram_staff_links",
                queryset=TelegramStaffLink.objects.filter(is_active=True).order_by(
                    "-linked_at",
                    "-pk",
                ),
                to_attr="active_telegram_links",
            ),
            Prefetch(
                "telegram_link_tokens",
                queryset=TelegramStaffLinkToken.objects.filter(
                    used_at__isnull=True,
                    revoked_at__isnull=True,
                    expires_at__gt=now,
                ).order_by("-created_at", "-pk"),
                to_attr="pending_telegram_link_tokens",
            ),
        )
        .annotate(
            has_active_telegram_link=Exists(active_link_query),
            has_pending_telegram_link_code=Exists(pending_link_code_query),
        )
        .order_by("is_active", "first_name", "last_name", "username", "pk")
    )


def _staff_profile_or_none(staff_user):
    try:
        return staff_user.staff_profile
    except StaffProfile.DoesNotExist:
        return None


def _decorate_staff_records(staff_users):
    """Attach UI-only, presentation-safe properties without database writes."""

    permission_details = {
        (
            permission.content_type.app_label,
            permission.codename,
        ): get_exception_permission_details(permission)
        for permission in get_assignable_exception_permissions()
    }
    role_tones = {
        StaffBusinessRole.SYSTEM_ADMINISTRATOR: "administrator",
        StaffBusinessRole.EMPLOYEE: "employee",
        StaffBusinessRole.CLEARANCE_EMPLOYEE: "clearance",
        StaffBusinessRole.EMPLOYEE_AND_CLEARANCE: "combined",
        StaffBusinessRole.UNASSIGNED: "unassigned",
    }

    for staff_user in staff_users:
        profile = _staff_profile_or_none(staff_user)
        role = get_staff_business_role(staff_user)
        capabilities = []

        for permission in staff_user.user_permissions.all():
            details = permission_details.get(
                (permission.content_type.app_label, permission.codename)
            )
            if details:
                capabilities.append(
                    {
                        "code": f"{permission.content_type.app_label}.{permission.codename}",
                        "label": details["label"],
                        "description": details["description"],
                    }
                )

        staff_user.panel_profile = profile
        staff_user.business_role = role
        staff_user.business_role_label = get_staff_business_role_label(staff_user)
        staff_user.business_role_tone = role_tones[role]
        staff_user.assigned_stage_list = (
            list(profile.assigned_stages.all()) if profile else []
        )
        staff_user.exceptional_capabilities = capabilities
        staff_user.current_telegram_link = (
            staff_user.active_telegram_links[0]
            if getattr(staff_user, "active_telegram_links", [])
            else None
        )
        staff_user.current_telegram_link_code = (
            staff_user.pending_telegram_link_tokens[0]
            if getattr(staff_user, "pending_telegram_link_tokens", [])
            else None
        )

    return staff_users


def _get_staff_list_context(request):
    user_model = get_user_model()
    query = (request.GET.get("q") or "").strip()
    selected_role = (request.GET.get("role") or "").strip()
    selected_status = (request.GET.get("status") or "").strip()
    selected_telegram = (request.GET.get("telegram") or "").strip()

    queryset = _internal_staff_queryset()

    if query:
        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(staff_profile__phone__icontains=query)
        )

    if selected_role == StaffBusinessRole.SYSTEM_ADMINISTRATOR:
        queryset = queryset.filter(is_superuser=True)
    elif selected_role == StaffBusinessRole.EMPLOYEE:
        queryset = queryset.filter(
            is_superuser=False,
            groups__name=RoleGroup.EMPLOYEE,
        ).exclude(groups__name=RoleGroup.CLEARANCE_EMPLOYEE)
    elif selected_role == StaffBusinessRole.CLEARANCE_EMPLOYEE:
        queryset = queryset.filter(
            is_superuser=False,
            groups__name=RoleGroup.CLEARANCE_EMPLOYEE,
        ).exclude(groups__name=RoleGroup.EMPLOYEE)
    elif selected_role == StaffBusinessRole.EMPLOYEE_AND_CLEARANCE:
        queryset = queryset.filter(
            is_superuser=False,
            groups__name=RoleGroup.EMPLOYEE,
        ).filter(groups__name=RoleGroup.CLEARANCE_EMPLOYEE)

    if selected_status == "active":
        queryset = queryset.filter(is_active=True)
    elif selected_status == "inactive":
        queryset = queryset.filter(is_active=False)

    if selected_telegram == "connected":
        queryset = queryset.filter(has_active_telegram_link=True)
    elif selected_telegram == "pending":
        queryset = queryset.filter(
            has_active_telegram_link=False,
            has_pending_telegram_link_code=True,
        )
    elif selected_telegram == "disconnected":
        queryset = queryset.filter(
            has_active_telegram_link=False,
            has_pending_telegram_link_code=False,
        )

    paginator = Paginator(queryset, _get_requested_per_page(request, default=20))
    page_obj = paginator.get_page(request.GET.get("page"))
    _decorate_staff_records(page_obj.object_list)

    directory_queryset = user_model.objects.filter(is_staff=True)
    return {
        "page_obj": page_obj,
        "result_count": paginator.count,
        "query": query,
        "selected_role": selected_role,
        "selected_status": selected_status,
        "selected_telegram": selected_telegram,
        "active_staff_count": directory_queryset.filter(
            is_active=True,
            is_superuser=False,
        ).count(),
        "employee_count": directory_queryset.filter(
            is_superuser=False,
            groups__name=RoleGroup.EMPLOYEE,
        ).distinct().count(),
        "clearance_staff_count": directory_queryset.filter(
            is_superuser=False,
            groups__name=RoleGroup.CLEARANCE_EMPLOYEE,
        ).distinct().count(),
        "combined_staff_count": directory_queryset.filter(
            is_superuser=False,
            groups__name=RoleGroup.EMPLOYEE,
        ).filter(
            groups__name=RoleGroup.CLEARANCE_EMPLOYEE,
        ).distinct().count(),
        "inactive_staff_count": directory_queryset.filter(
            is_active=False,
            is_superuser=False,
        ).count(),
    }


def _get_staff_member_or_404(pk, *, manageable_only=False):
    queryset = _internal_staff_queryset()
    if manageable_only:
        queryset = queryset.filter(is_superuser=False)
    staff_user = get_object_or_404(queryset, pk=pk)
    _decorate_staff_records([staff_user])
    return staff_user


def _staff_form_service_data(form):
    return {
        "username": form.cleaned_data["username"],
        "first_name": form.cleaned_data["first_name"],
        "last_name": form.cleaned_data["last_name"],
        "email": form.cleaned_data["email"],
        "phone": form.cleaned_data["phone"],
        "role": form.cleaned_data["role"],
        "assigned_stages": form.cleaned_data["assigned_stages"],
        "exceptional_permissions": form.cleaned_data["exceptional_permissions"],
    }


@system_administrator_required
def staff_list(request):
    return render(
        request,
        "backoffice/staff/list.html",
        _get_staff_list_context(request),
    )


@system_administrator_required
def staff_create(request):
    if request.method == "POST":
        form = StaffAccountForm(request.POST, include_password=True)

        if form.is_valid():
            try:
                staff_user = create_staff_member(
                    actor=request.user,
                    raw_password=form.cleaned_data["password1"],
                    **_staff_form_service_data(form),
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"حساب کارمند «{staff_user.get_full_name() or staff_user.username}» ایجاد شد.",
                )
                return redirect("backoffice:staff_detail", pk=staff_user.pk)
    else:
        form = StaffAccountForm(include_password=True)

    return render(
        request,
        "backoffice/staff/form.html",
        {
            "form": form,
            "form_title": "افزودن کارمند",
            "submit_label": "ایجاد حساب کارمند",
            "notice": (
                "حساب جدید با نقش پایه، دسترسی‌های کنترل‌شده و پروفایل مسئولیت مراحل ساخته می‌شود. "
                "رمز عبور فقط یک‌بار توسط مدیر تعیین می‌شود و هرگز در تاریخچه ذخیره نخواهد شد."
            ),
            "is_create": True,
        },
    )


@system_administrator_required
def staff_detail(request, pk):
    staff_user = _get_staff_member_or_404(pk)

    staff_events = list(
        StaffManagementEvent.objects.filter(staff_user=staff_user)
        .select_related("performed_by")
        .order_by("-created_at", "-pk")[:12]
    )
    tracking_events = list(
        TrackingEvent.objects.filter(performed_by=staff_user)
        .select_related("car", "previous_stage", "new_stage")
        .order_by("-created_at", "-pk")[:8]
    )
    inventory_events = list(
        VehicleInventoryEvent.objects.filter(performed_by=staff_user)
        .select_related("car")
        .order_by("-created_at", "-pk")[:8]
    )

    activity = []
    tracking_labels = {
        TrackingEvent.EventType.TRACKING_STARTED: "شروع رهگیری ماشین",
        TrackingEvent.EventType.STAGE_CONFIRMED: "ورود ماشین به مرحله",
        TrackingEvent.EventType.STAGE_COMPLETED: "تکمیل مرحلهٔ تحویل",
        TrackingEvent.EventType.STAGE_CORRECTED: "اصلاح مرحلهٔ تحویل",
        TrackingEvent.EventType.STAGE_SKIPPED: "ردکردن مرحلهٔ تحویل",
        TrackingEvent.EventType.STAGE_ARCHIVED: "تغییر ناشی از بایگانی مرحله",
    }
    for event in tracking_events:
        activity.append(
            {
                "timestamp": event.created_at,
                "icon": "fa-map-marker",
                "tone": "tracking",
                "title": tracking_labels.get(event.event_type, event.event_type),
                "description": f"ماشین: {event.car.title}",
            }
        )

    inventory_labels = {
        VehicleInventoryEvent.Action.CREATED: "ثبت ماشین در موجودی",
        VehicleInventoryEvent.Action.UPDATED: "ویرایش اطلاعات ماشین",
    }
    for event in inventory_events:
        activity.append(
            {
                "timestamp": event.created_at,
                "icon": "fa-car",
                "tone": "inventory",
                "title": inventory_labels.get(event.action, event.action),
                "description": f"ماشین: {event.car.title}",
            }
        )

    staff_event_labels = {
        StaffManagementEvent.Action.CREATED: "ایجاد حساب کارمند",
        StaffManagementEvent.Action.UPDATED: "ویرایش حساب و دسترسی‌ها",
        StaffManagementEvent.Action.PASSWORD_RESET: "تغییر رمز عبور",
        StaffManagementEvent.Action.DEACTIVATED: "غیرفعال‌سازی حساب",
        StaffManagementEvent.Action.REACTIVATED: "فعال‌سازی دوبارهٔ حساب",
        StaffManagementEvent.Action.TELEGRAM_LINK_ISSUED: "صدور کد اتصال Telegram",
        StaffManagementEvent.Action.TELEGRAM_LINK_REVOKED: "لغو اتصال Telegram",
    }
    for event in staff_events:
        activity.append(
            {
                "timestamp": event.created_at,
                "icon": "fa-shield",
                "tone": "management",
                "title": staff_event_labels.get(event.action, event.action),
                "description": (
                    f"توسط {event.performed_by.get_full_name() or event.performed_by.username}"
                ),
            }
        )

    activity.sort(key=lambda item: item["timestamp"], reverse=True)

    return render(
        request,
        "backoffice/staff/detail.html",
        {
            "staff_user": staff_user,
            "staff_events": staff_events,
            "activity": activity[:16],
            "all_permissions_count": (
                "همهٔ دسترسی‌ها"
                if staff_user.is_superuser
                else len(staff_user.get_all_permissions())
            ),
            "exception_permission_descriptions": [
                get_exception_permission_details(permission)
                for permission in staff_user.user_permissions.all()
                if get_exception_permission_details(permission)
            ],
        },
    )


@system_administrator_required
def staff_edit(request, pk):
    staff_user = _get_staff_member_or_404(pk, manageable_only=True)

    if request.method == "POST":
        form = StaffAccountForm(request.POST, staff_user=staff_user)

        if form.is_valid():
            try:
                updated_staff_user = update_staff_member(
                    staff_user=staff_user,
                    actor=request.user,
                    **_staff_form_service_data(form),
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(request, "اطلاعات، نقش و دسترسی‌های کارمند به‌روزرسانی شد.")
                return redirect("backoffice:staff_detail", pk=updated_staff_user.pk)
    else:
        form = StaffAccountForm(staff_user=staff_user)

    return render(
        request,
        "backoffice/staff/form.html",
        {
            "form": form,
            "staff_user": staff_user,
            "form_title": (
                f"ویرایش کارمند «{staff_user.get_full_name() or staff_user.username}»"
            ),
            "submit_label": "ذخیرهٔ تغییرات",
            "notice": (
                "تغییر نقش یا دسترسی ویژه بلافاصله روی وب‌سایت، عملیات Excel و Telegram اعمال می‌شود. "
                "اگر دسترسی تأیید مرحله برداشته شود، تخصیص مرحله‌های کارمند نیز حذف می‌شود."
            ),
            "is_create": False,
        },
    )


@system_administrator_required
def staff_password_reset(request, pk):
    staff_user = _get_staff_member_or_404(pk, manageable_only=True)

    if request.method == "POST":
        form = StaffPasswordResetForm(request.POST, staff_user=staff_user)

        if form.is_valid():
            try:
                reset_staff_password(
                    staff_user=staff_user,
                    actor=request.user,
                    raw_password=form.cleaned_data["new_password1"],
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    "رمز عبور کارمند تغییر کرد. رمز جدید فقط باید از یک کانال امن در اختیار او قرار گیرد.",
                )
                return redirect("backoffice:staff_detail", pk=staff_user.pk)
    else:
        form = StaffPasswordResetForm(staff_user=staff_user)

    return render(
        request,
        "backoffice/staff/password_form.html",
        {
            "form": form,
            "staff_user": staff_user,
        },
    )


@system_administrator_required
def staff_status(request, pk):
    staff_user = _get_staff_member_or_404(pk, manageable_only=True)
    next_is_active = not staff_user.is_active
    action_label = "فعال‌سازی" if next_is_active else "غیرفعال‌سازی"

    if request.method == "POST":
        form = StaffStatusChangeForm(request.POST)

        if form.is_valid():
            try:
                set_staff_active_state(
                    staff_user=staff_user,
                    actor=request.user,
                    is_active=next_is_active,
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(
                    request,
                    f"حساب «{staff_user.get_full_name() or staff_user.username}» {action_label} شد.",
                )
                return redirect("backoffice:staff_detail", pk=staff_user.pk)
    else:
        form = StaffStatusChangeForm()

    return render(
        request,
        "backoffice/staff/status_confirm.html",
        {
            "form": form,
            "staff_user": staff_user,
            "next_is_active": next_is_active,
            "action_label": action_label,
        },
    )


@system_administrator_required
@require_POST
def staff_telegram_link_issue(request, pk):
    staff_user = _get_staff_member_or_404(pk, manageable_only=True)

    try:
        result = issue_staff_telegram_link_code(
            staff_user=staff_user,
            actor=request.user,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return redirect("backoffice:staff_detail", pk=staff_user.pk)

    return render(
        request,
        "backoffice/staff/telegram_link_code.html",
        {
            "staff_user": staff_user,
            "telegram_link_code": result["code"],
            "expires_at": result["expires_at"],
        },
    )


@system_administrator_required
def staff_telegram_link_revoke(request, pk):
    staff_user = _get_staff_member_or_404(pk, manageable_only=True)

    if staff_user.current_telegram_link is None:
        messages.info(request, "برای این کارمند اتصال فعال Telegram وجود ندارد.")
        return redirect("backoffice:staff_detail", pk=staff_user.pk)

    if request.method == "POST":
        form = StaffTelegramRevokeForm(request.POST)

        if form.is_valid():
            try:
                revoke_staff_telegram_link(
                    staff_user=staff_user,
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(request, "اتصال Telegram کارمند با موفقیت لغو شد.")
                return redirect("backoffice:staff_detail", pk=staff_user.pk)
    else:
        form = StaffTelegramRevokeForm()

    return render(
        request,
        "backoffice/staff/telegram_revoke_confirm.html",
        {
            "form": form,
            "staff_user": staff_user,
        },
    )


@system_administrator_required
def staff_role_guide(request):
    return render(
        request,
        "backoffice/staff/role_guide.html",
        {
            "roles": [
                {
                    "icon": "fa-briefcase",
                    "name": "کارمند",
                    "description": (
                        "مدیریت موجودی ماشین، تصاویر، وبلاگ، تنظیمات محتوایی سایت و مشاهدهٔ درخواست‌های مشتری."
                    ),
                    "capabilities": [
                        "ثبت، ویرایش و انتشار ماشین‌ها",
                        "مدیریت تصاویر و نمای ۳۶۰ درجه",
                        "مدیریت مقاله‌های وبلاگ و محتوای سایت",
                        "مشاهدهٔ درخواست‌های اختصاصی مشتریان",
                    ],
                },
                {
                    "icon": "fa-truck",
                    "name": "کارمند ترخیص",
                    "description": (
                        "تأیید مرحله‌های تحویل و پردازش گروهی Excel، مشروط به تخصیص مرحله توسط مدیر اصلی؛ بدون دسترسی به مدیریت موجودی و تصاویر ماشین‌ها."
                    ),
                    "capabilities": [
                        "تأیید ورود ماشین به مرحلهٔ اختصاص‌یافته",
                        "مشاهدهٔ مسیر، تاریخچه و وضعیت رهگیری",
                        "بارگذاری Excel برای به‌روزرسانی‌های مرحله‌ای",
                        "استفاده از همان منطق مشترک از پنل و Telegram",
                    ],
                },
                {
                    "icon": "fa-random",
                    "name": "کارمند + کارمند ترخیص",
                    "description": (
                        "برای کارمندی که باید هم موجودی و محتوای سایت را مدیریت کند و هم در مرحله‌های مشخص عملیات تحویل انجام دهد."
                    ),
                    "capabilities": [
                        "تمام قابلیت‌های نقش کارمند برای مدیریت ماشین، تصاویر و محتوا",
                        "صف عملیاتی و تأیید مرحله فقط در مرحله‌های تخصیص‌یافته",
                        "ثبت گروهی Excel با همان کنترل‌های مجوز و مرحله",
                        "نمایش یک نقش ترکیبی شفاف در پرونده و فهرست کارکنان",
                    ],
                },
            ],
            "special_permissions": [
                {
                    "label": details["label"],
                    "description": details["description"],
                }
                for permission in get_assignable_exception_permissions()
                for details in [get_exception_permission_details(permission)]
            ],
        },
    )
