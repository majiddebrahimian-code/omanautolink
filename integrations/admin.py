from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path

from .forms import (
    TelegramCustomerActivationCodeForm,
    TelegramStaffLinkCodeForm,
)
from .models import (
    CustomerTelegramSubscription,
    CustomerTrackingNotification,
    TelegramCustomerActivationToken,
    TelegramInboundUpdate,
    TelegramOutboxMessage,
    TelegramStageConfirmationSession,
    TelegramStaffLink,
    TelegramStaffLinkToken,
)
from .services import (
    create_customer_telegram_activation_code,
    create_telegram_staff_link_code,
    revoke_telegram_staff_link,
)


class SystemAdministratorOnlyAdmin(admin.ModelAdmin):
    """Integration data contains security/audit information and is superuser-only."""

    def _is_system_administrator(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_module_permission(self, request):
        return self._is_system_administrator(request)

    def has_view_permission(self, request, obj=None):
        return self._is_system_administrator(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TelegramStaffLink)
class TelegramStaffLinkAdmin(SystemAdministratorOnlyAdmin):
    change_list_template = "admin/integrations/telegramstafflink/change_list.html"

    list_display = [
        "user",
        "telegram_user_id",
        "telegram_chat_id",
        "telegram_username",
        "is_active",
        "linked_at",
        "last_seen_at",
    ]
    list_filter = ["is_active", "linked_at"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "telegram_username"]
    list_select_related = ["user", "unlinked_by"]
    readonly_fields = [
        "user",
        "telegram_user_id",
        "telegram_chat_id",
        "telegram_username",
        "first_name",
        "last_name",
        "is_active",
        "linked_at",
        "last_seen_at",
        "unlinked_at",
        "unlinked_by",
        "unlink_reason",
    ]
    actions = ["revoke_selected_links"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "unlinked_by")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "issue-link-code/",
                self.admin_site.admin_view(self.issue_link_code_view),
                name="integrations_telegramstafflink_issue_link_code",
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["issue_link_code_url"] = "issue-link-code/"
        return super().changelist_view(request, extra_context=extra_context)

    def issue_link_code_view(self, request):
        if not self._is_system_administrator(request):
            raise PermissionDenied

        if request.method == "POST":
            form = TelegramStaffLinkCodeForm(request.POST)

            if form.is_valid():
                result = create_telegram_staff_link_code(
                    staff_user=form.cleaned_data["staff_user"],
                    actor=request.user,
                )
                context = {
                    **self.admin_site.each_context(request),
                    "title": "کد اتصال تلگرام ایجاد شد",
                    "opts": self.model._meta,
                    "staff_user": form.cleaned_data["staff_user"],
                    "raw_code": result["code"],
                    "expires_at": result["expires_at"],
                }
                return TemplateResponse(
                    request,
                    "admin/integrations/telegramstafflink/link_code_created.html",
                    context,
                )
        else:
            form = TelegramStaffLinkCodeForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "صدور کد اتصال تلگرام برای کارمند",
            "opts": self.model._meta,
            "form": form,
        }
        return TemplateResponse(
            request,
            "admin/integrations/telegramstafflink/issue_link_code.html",
            context,
        )

    @admin.action(description="لغو اتصال‌های تلگرام انتخاب‌شده")
    def revoke_selected_links(self, request, queryset):
        revoked_count = 0

        for staff_link in queryset.filter(is_active=True):
            revoke_telegram_staff_link(
                staff_link=staff_link,
                actor=request.user,
                reason="لغو از طریق پنل مدیریت.",
            )
            revoked_count += 1

        if revoked_count:
            self.message_user(
                request,
                f"{revoked_count} اتصال تلگرام لغو شد.",
                level=messages.SUCCESS,
            )


@admin.register(TelegramStaffLinkToken)
class TelegramStaffLinkTokenAdmin(SystemAdministratorOnlyAdmin):
    list_display = [
        "user",
        "created_by",
        "created_at",
        "expires_at",
        "used_at",
        "revoked_at",
        "attempt_count",
    ]
    list_filter = ["created_at", "used_at", "revoked_at"]
    search_fields = ["user__username", "created_by__username"]
    list_select_related = ["user", "created_by", "revoked_by"]
    readonly_fields = [
        "user",
        "code_hash",
        "created_by",
        "created_at",
        "expires_at",
        "used_at",
        "used_telegram_user_id",
        "revoked_at",
        "revoked_by",
        "attempt_count",
    ]


class CustomerActivationIssuerAdmin(admin.ModelAdmin):
    """Limited admin access for the explicit customer-code issuer permission."""

    def _can_issue_customer_activation(self, request):
        return bool(
            request.user.is_active
            and request.user.is_staff
            and request.user.has_perm(
                "integrations.issue_customer_telegram_activation"
            )
        )

    def has_module_permission(self, request):
        return self._can_issue_customer_activation(request)

    def has_view_permission(self, request, obj=None):
        return self._can_issue_customer_activation(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TelegramCustomerActivationToken)
class TelegramCustomerActivationTokenAdmin(CustomerActivationIssuerAdmin):
    change_list_template = (
        "admin/integrations/telegramcustomeractivationtoken/change_list.html"
    )

    list_display = [
        "car",
        "customer",
        "created_by",
        "created_at",
        "expires_at",
        "used_at",
        "revoked_at",
        "attempt_count",
    ]
    list_filter = ["created_at", "used_at", "revoked_at"]
    search_fields = [
        "car__tracking_code",
        "car__title",
        "customer__full_name",
        "created_by__username",
    ]
    list_select_related = ["car", "customer", "created_by", "revoked_by"]
    readonly_fields = [
        "car",
        "customer",
        "code_hash",
        "created_by",
        "created_at",
        "expires_at",
        "used_at",
        "used_telegram_user_id",
        "revoked_at",
        "revoked_by",
        "attempt_count",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "car",
            "customer",
            "created_by",
            "revoked_by",
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "issue-customer-activation-code/",
                self.admin_site.admin_view(self.issue_customer_activation_code_view),
                name=(
                    "integrations_telegramcustomeractivationtoken_"
                    "issue_customer_activation_code"
                ),
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["issue_customer_activation_code_url"] = (
            "issue-customer-activation-code/"
        )
        return super().changelist_view(request, extra_context=extra_context)

    def issue_customer_activation_code_view(self, request):
        if not self._can_issue_customer_activation(request):
            raise PermissionDenied

        if request.method == "POST":
            form = TelegramCustomerActivationCodeForm(request.POST)

            if form.is_valid():
                result = create_customer_telegram_activation_code(
                    car=form.cleaned_data["car"],
                    actor=request.user,
                )
                context = {
                    **self.admin_site.each_context(request),
                    "title": "کد فعال‌سازی مشتری ایجاد شد",
                    "opts": self.model._meta,
                    "car": form.cleaned_data["car"],
                    "customer": form.cleaned_data["car"].customer,
                    "raw_code": result["code"],
                    "expires_at": result["expires_at"],
                }
                return TemplateResponse(
                    request,
                    (
                        "admin/integrations/telegramcustomeractivationtoken/"
                        "activation_code_created.html"
                    ),
                    context,
                )
        else:
            form = TelegramCustomerActivationCodeForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "صدور کد فعال‌سازی ربات برای مشتری",
            "opts": self.model._meta,
            "form": form,
        }
        return TemplateResponse(
            request,
            (
                "admin/integrations/telegramcustomeractivationtoken/"
                "issue_activation_code.html"
            ),
            context,
        )


@admin.register(TelegramInboundUpdate)
class TelegramInboundUpdateAdmin(SystemAdministratorOnlyAdmin):
    list_display = [
        "telegram_update_id",
        "update_type",
        "command_name",
        "staff_link",
        "customer_subscription",
        "status",
        "received_at",
        "processed_at",
    ]
    list_filter = ["update_type", "status", "received_at"]
    search_fields = [
        "telegram_update_id",
        "telegram_user_id",
        "telegram_chat_id",
        "staff_link__user__username",
        "customer_subscription__car__tracking_code",
    ]
    list_select_related = [
        "staff_link",
        "staff_link__user",
        "customer_subscription",
        "customer_subscription__car",
    ]
    readonly_fields = [
        "telegram_update_id",
        "telegram_user_id",
        "telegram_chat_id",
        "telegram_message_id",
        "update_type",
        "command_name",
        "staff_link",
        "customer_subscription",
        "status",
        "error_summary",
        "received_at",
        "processed_at",
    ]


@admin.register(TelegramStageConfirmationSession)
class TelegramStageConfirmationSessionAdmin(SystemAdministratorOnlyAdmin):
    list_display = ["public_token", "staff_link", "car", "stage", "status", "created_at", "expires_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["public_token", "car__tracking_code", "car__title", "staff_link__user__username"]
    list_select_related = ["staff_link", "staff_link__user", "car", "stage"]
    readonly_fields = [
        "public_token",
        "staff_link",
        "car",
        "stage",
        "status",
        "created_at",
        "expires_at",
        "confirmed_at",
        "cancelled_at",
        "failure_reason",
    ]


@admin.register(TelegramOutboxMessage)
class TelegramOutboxMessageAdmin(SystemAdministratorOnlyAdmin):
    list_display = [
        "id",
        "operation",
        "message_type",
        "staff_link",
        "customer_subscription",
        "status",
        "attempt_count",
        "created_at",
        "sent_at",
    ]
    list_filter = ["operation", "status", "message_type", "created_at"]
    search_fields = [
        "idempotency_key",
        "chat_id",
        "staff_link__user__username",
        "customer_subscription__car__tracking_code",
    ]
    list_select_related = [
        "staff_link",
        "staff_link__user",
        "customer_subscription",
        "customer_subscription__car",
        "inbound_update",
    ]
    readonly_fields = [
        "operation",
        "chat_id",
        "callback_query_id",
        "body",
        "reply_markup",
        "reply_to_message_id",
        "message_type",
        "idempotency_key",
        "inbound_update",
        "staff_link",
        "customer_subscription",
        "status",
        "attempt_count",
        "next_attempt_at",
        "delivery_started_at",
        "sent_at",
        "telegram_message_id",
        "last_error_summary",
        "created_at",
    ]


@admin.register(CustomerTelegramSubscription)
class CustomerTelegramSubscriptionAdmin(SystemAdministratorOnlyAdmin):
    list_display = [
        "car",
        "customer",
        "telegram_user_id",
        "telegram_chat_id",
        "is_active",
        "subscribed_at",
        "last_seen_at",
        "unsubscribed_at",
    ]
    list_filter = ["is_active", "subscribed_at", "unsubscribed_at"]
    search_fields = [
        "car__tracking_code",
        "car__title",
        "customer__full_name",
        "telegram_user_id",
        "telegram_chat_id",
    ]
    list_select_related = ["car", "customer"]
    readonly_fields = [
        "car",
        "customer",
        "telegram_user_id",
        "telegram_chat_id",
        "telegram_username",
        "first_name",
        "last_name",
        "is_active",
        "subscribed_at",
        "last_seen_at",
        "unsubscribed_at",
        "unsubscribe_reason",
    ]


@admin.register(CustomerTrackingNotification)
class CustomerTrackingNotificationAdmin(SystemAdministratorOnlyAdmin):
    list_display = [
        "tracking_event",
        "subscription",
        "outbox_message",
        "created_at",
    ]
    list_filter = ["created_at"]
    search_fields = [
        "tracking_event__car__tracking_code",
        "subscription__car__tracking_code",
        "outbox_message__idempotency_key",
    ]
    list_select_related = [
        "tracking_event",
        "tracking_event__car",
        "subscription",
        "subscription__car",
        "outbox_message",
    ]
    readonly_fields = [
        "tracking_event",
        "subscription",
        "outbox_message",
        "created_at",
    ]
