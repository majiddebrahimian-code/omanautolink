from django import forms
from django.db import models
from django.db.models import Q

from accounts.models import StaffProfile


def _eligible_stage_staff_profiles():
    """Return internal users who can actually confirm a tracking stage.

    Assignment alone must never grant a general employee operational stage
    authority.  This mirrors the authorization rule enforced by
    ``require_stage_confirmation_permission`` in the service layer.
    """

    return (
        StaffProfile.objects.select_related("user")
        .filter(
            user__is_active=True,
            user__is_staff=True,
        )
        .filter(
            Q(user__is_superuser=True)
            | Q(
                user__user_permissions__content_type__app_label="tracking",
                user__user_permissions__codename="confirm_tracking_stage",
            )
            | Q(
                user__groups__permissions__content_type__app_label="tracking",
                user__groups__permissions__codename="confirm_tracking_stage",
            )
        )
        .distinct()
        .order_by("user__first_name", "user__last_name", "user__username")
    )


class PublicTrackingLookupForm(forms.Form):
    tracking_code = forms.CharField(
        label="کد رهگیری",
        max_length=40,
        strip=True,
        error_messages={
            "required": "لطفاً کد رهگیری را وارد کنید.",
        },
        widget=forms.TextInput(
            attrs={
                "placeholder": "مثال: OAL-...",
                "autocomplete": "off",
                "dir": "ltr",
            }
        ),
    )


class ClearanceTrackingCodeForm(forms.Form):
    """Adapter form for an internal stage operation.

    The form does not decide which stage may change. The service layer owns
    workflow validation and employee authorization.
    """

    class Operation(models.TextChoices):
        ENTER = "enter", "ثبت ورود به مرحله"
        COMPLETE = "complete", "تکمیل مرحلهٔ فعلی"

    tracking_code = forms.CharField(
        label="کد رهگیری",
        max_length=40,
        widget=forms.TextInput(
            attrs={
                "class": "backoffice-input",
                "placeholder": "مثال: OAL-...",
                "autocomplete": "off",
                "dir": "ltr",
            }
        ),
    )
    operation = forms.ChoiceField(
        label="عملیات",
        choices=Operation.choices,
        widget=forms.Select(attrs={"class": "backoffice-select"}),
    )


class ClearanceConfirmationForm(forms.Form):
    """Requires a second, explicit confirmation before a tracking write."""

    tracking_code = forms.CharField(widget=forms.HiddenInput())
    operation = forms.ChoiceField(
        choices=ClearanceTrackingCodeForm.Operation.choices,
        widget=forms.HiddenInput(),
    )
    confirm_operation = forms.BooleanField(
        label="اطلاعات خودرو و مرحله را بررسی کرده‌ام و این عملیات را تأیید می‌کنم.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "backoffice-checkbox"}),
    )


class StageDefinitionForm(forms.Form):
    """The restricted panel form for safe linear-stage configuration."""

    name = forms.CharField(
        label="نام مرحله",
        max_length=120,
        widget=forms.TextInput(
            attrs={
                "class": "backoffice-input",
                "placeholder": "مثلاً ترخیص گمرک",
            }
        ),
        error_messages={"required": "نام مرحله را وارد کنید."},
    )
    duration_from_previous = forms.IntegerField(
        label="مدت انتقال از مرحلهٔ قبلی (روز)",
        min_value=0,
        required=False,
        widget=forms.NumberInput(
            attrs={
                "class": "backoffice-input",
                "min": 0,
                "step": 1,
                "placeholder": "مثلاً ۵",
            }
        ),
        help_text=(
            "ETA از مدت انتقال بین دو مرحله محاسبه می‌شود؛ "
            "برای اولین مرحله مقداری لازم نیست."
        ),
    )
    assigned_staff = forms.ModelMultipleChoiceField(
        label="کارمندان مسئول مرحله",
        queryset=StaffProfile.objects.none(),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "backoffice-select-multiple",
                "size": 6,
            }
        ),
        help_text=(
            "فقط کاربران فعال دارای مجوز تأیید مرحله نمایش داده می‌شوند. "
            "امکان انتخاب چند کارمند وجود دارد."
        ),
    )

    def __init__(self, *args, stage=None, previous_stage=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_staff"].queryset = _eligible_stage_staff_profiles()

        if stage is not None:
            self.initial.setdefault("name", stage.name)
            self.initial.setdefault(
                "assigned_staff",
                stage.staff_members.values_list("pk", flat=True),
            )

        if previous_stage is None:
            self.fields["duration_from_previous"].help_text = (
                "این مرحله، اولین مرحلهٔ فعال مسیر است؛ زمان انتقال قبلی ندارد."
            )
        else:
            self.fields["duration_from_previous"].required = True
            self.fields["duration_from_previous"].help_text = (
                f"مدت زمان حرکت از «{previous_stage.name}» به این مرحله. "
                "تغییر آن ETA خودروهای درحال‌تحویل را به‌صورت پویا به‌روزرسانی می‌کند."
            )


class StageArchiveForm(forms.Form):
    """Collect the confirmation and operational data required for soft archive."""

    replacement_duration_days = forms.IntegerField(
        label="مدت انتقال جایگزین بین مرحلهٔ قبلی و بعدی (روز)",
        min_value=0,
        widget=forms.NumberInput(
            attrs={
                "class": "backoffice-input",
                "min": 0,
                "step": 1,
            }
        ),
        help_text=(
            "پس از بایگانی، این زمان برای Transition جدید بین دو مرحلهٔ مجاور استفاده می‌شود."
        ),
    )
    note = forms.CharField(
        label="دلیل بایگانی",
        max_length=1000,
        widget=forms.Textarea(
            attrs={
                "class": "backoffice-textarea",
                "rows": 4,
                "placeholder": "دلیل و اثر مورد انتظار این تغییر را ثبت کنید.",
            }
        ),
        error_messages={"required": "ثبت دلیل بایگانی الزامی است."},
    )
    confirm_affected_vehicles = forms.BooleanField(
        label="اثر این تغییر روی ماشین‌های فهرست‌شده را بررسی کرده‌ام و تأیید می‌کنم.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "backoffice-checkbox"}),
        error_messages={
            "required": "برای بایگانی مرحله باید اثر آن بر ماشین‌ها را تأیید کنید."
        },
    )


class TransitionRepairForm(forms.Form):
    """Collect explicit ETA values while repairing a legacy stage route."""

    confirm_route_repair = forms.BooleanField(
        label=(
            "اتصال‌های نمایش‌داده‌شده و اثر زمان‌بندی جدید بر ETA ماشین‌های در حال تحویل را بررسی کرده‌ام و می‌پذیرم که Transitionهای غیرخطیِ احتمالی فقط غیرفعال شوند."
        ),
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "backoffice-checkbox"}),
        error_messages={
            "required": "برای ترمیم مسیر، تأیید صریح مدیر سیستم لازم است."
        },
    )

    def __init__(self, *args, route_integrity, **kwargs):
        super().__init__(*args, **kwargs)
        self.route_integrity = route_integrity
        self.duration_field_names = []

        for pair in route_integrity["pairs"]:
            from_stage = pair["from_stage"]
            to_stage = pair["to_stage"]
            field_name = f"duration_to_stage_{to_stage.pk}"
            stored_transition = pair["stored_transition"]
            initial_duration = (
                stored_transition.estimated_duration_days
                if stored_transition is not None
                else to_stage.default_duration_days
            )

            self.fields[field_name] = forms.IntegerField(
                label=f"مدت انتقال از «{from_stage.name}» به «{to_stage.name}» (روز)",
                min_value=0,
                initial=initial_duration,
                widget=forms.NumberInput(
                    attrs={
                        "class": "backoffice-input",
                        "min": 0,
                        "step": 1,
                    }
                ),
                help_text=(
                    "این زمان در ETA ماشین‌های در حال تحویل به‌صورت پویا استفاده می‌شود."
                ),
            )
            self.duration_field_names.append(field_name)

        self.order_fields([
            *self.duration_field_names,
            "confirm_route_repair",
        ])

    def get_transition_durations(self):
        """Return a domain-friendly map keyed by (from_stage_id, to_stage_id)."""

        return {
            (pair["from_stage"].pk, pair["to_stage"].pk): self.cleaned_data[
                f"duration_to_stage_{pair['to_stage'].pk}"
            ]
            for pair in self.route_integrity["pairs"]
        }
