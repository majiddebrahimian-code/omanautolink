from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from accounts.models import StaffProfile
from accounts.services import (
    StaffBusinessRole,
    get_assignable_exception_permissions,
    get_exception_permission_details,
    get_staff_business_role,
)
from tracking.models import Stage


class ExceptionalPermissionMultipleChoiceField(forms.ModelMultipleChoiceField):
    """Show business labels instead of raw Django permission names."""

    def label_from_instance(self, permission):
        details = get_exception_permission_details(permission)
        return details.get("label", permission.name)


class StaffAccountForm(forms.Form):
    """Controlled employee form; it intentionally does not expose raw groups."""

    username = forms.CharField(
        label="نام کاربری",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "backoffice-input",
                "autocomplete": "username",
                "dir": "ltr",
                "placeholder": "مثلاً ali.sales",
            }
        ),
    )
    first_name = forms.CharField(
        label="نام",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "backoffice-input"}),
    )
    last_name = forms.CharField(
        label="نام خانوادگی",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "backoffice-input"}),
    )
    email = forms.EmailField(
        label="ایمیل",
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "backoffice-input",
                "autocomplete": "email",
                "dir": "ltr",
            }
        ),
    )
    phone = forms.CharField(
        label="شماره تماس",
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "backoffice-input",
                "autocomplete": "tel",
                "dir": "ltr",
                "placeholder": "مثلاً 09120000000",
            }
        ),
    )
    role = forms.ChoiceField(
        label="نقش عملیاتی",
        choices=StaffBusinessRole.MANAGEABLE_CHOICES,
        widget=forms.Select(attrs={"class": "backoffice-select"}),
        help_text="هر کارمند دقیقاً یک نقش پایه دریافت می‌کند.",
    )
    assigned_stages = forms.ModelMultipleChoiceField(
        label="مرحله‌های تحویل مسئول",
        queryset=Stage.objects.none(),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "backoffice-select-multiple",
                "size": 6,
            }
        ),
        help_text=(
            "برای کارمند ترخیص فعال است. برای کارمند عادی، ابتدا دسترسی ویژهٔ "
            "«تأیید مرحلهٔ تحویل» را انتخاب کنید."
        ),
    )
    exceptional_permissions = ExceptionalPermissionMultipleChoiceField(
        label="دسترسی‌های ویژه",
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "backoffice-checkbox"}
        ),
        help_text=(
            "این موارد علاوه بر مجوزهای نقش پایه هستند و فقط برای این کارمند اعمال می‌شوند."
        ),
    )

    def __init__(self, *args, staff_user=None, include_password=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff_user = staff_user
        self.include_password = include_password
        self.fields["assigned_stages"].queryset = Stage.objects.filter(
            is_active=True
        ).order_by("order", "pk")
        self.fields["exceptional_permissions"].queryset = (
            get_assignable_exception_permissions()
        )

        if include_password:
            self.fields["password1"] = forms.CharField(
                label="رمز عبور اولیه",
                strip=False,
                widget=forms.PasswordInput(
                    attrs={
                        "class": "backoffice-input",
                        "autocomplete": "new-password",
                        "dir": "ltr",
                    }
                ),
                help_text="رمز عبور هرگز در پنل یا تاریخچه ذخیره و نمایش داده نمی‌شود.",
            )
            self.fields["password2"] = forms.CharField(
                label="تکرار رمز عبور اولیه",
                strip=False,
                widget=forms.PasswordInput(
                    attrs={
                        "class": "backoffice-input",
                        "autocomplete": "new-password",
                        "dir": "ltr",
                    }
                ),
            )

        if staff_user is not None and not self.is_bound:
            profile = StaffProfile.objects.filter(user=staff_user).first()
            role = get_staff_business_role(staff_user)
            allowed_permission_ids = list(
                get_assignable_exception_permissions().values_list("pk", flat=True)
            )
            self.initial.update(
                {
                    "username": staff_user.username,
                    "first_name": staff_user.first_name,
                    "last_name": staff_user.last_name,
                    "email": staff_user.email,
                    "phone": profile.phone if profile else "",
                    "role": (
                        role
                        if role in dict(StaffBusinessRole.MANAGEABLE_CHOICES)
                        else StaffBusinessRole.EMPLOYEE
                    ),
                    "assigned_stages": (
                        profile.assigned_stages.filter(is_active=True).values_list(
                            "pk", flat=True
                        )
                        if profile
                        else []
                    ),
                    "exceptional_permissions": staff_user.user_permissions.filter(
                        pk__in=allowed_permission_ids
                    ).values_list("pk", flat=True),
                }
            )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        user_model = get_user_model()
        users = user_model.objects.filter(username__iexact=username)

        if self.staff_user is not None:
            users = users.exclude(pk=self.staff_user.pk)

        if users.exists():
            raise forms.ValidationError("این نام کاربری قبلاً استفاده شده است.")

        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if not email:
            return ""

        user_model = get_user_model()
        users = user_model.objects.filter(email__iexact=email)

        if self.staff_user is not None:
            users = users.exclude(pk=self.staff_user.pk)

        if users.exists():
            raise forms.ValidationError("این ایمیل قبلاً برای یک حساب دیگر ثبت شده است.")

        return email

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        assigned_stages = cleaned_data.get("assigned_stages")
        exceptional_permissions = cleaned_data.get("exceptional_permissions")

        if assigned_stages:
            has_direct_confirmation_permission = bool(
                exceptional_permissions
                and exceptional_permissions.filter(
                    content_type__app_label="tracking",
                    codename="confirm_tracking_stage",
                ).exists()
            )
            has_inherited_confirmation_permission = (
                role == StaffBusinessRole.CLEARANCE_EMPLOYEE
            )

            if not (
                has_direct_confirmation_permission
                or has_inherited_confirmation_permission
            ):
                self.add_error(
                    "assigned_stages",
                    "برای تخصیص مرحله، نقش «کارمند ترخیص» یا دسترسی ویژهٔ تأیید مرحله لازم است.",
                )

        if self.include_password:
            password1 = cleaned_data.get("password1")
            password2 = cleaned_data.get("password2")

            if password1 and password2 and password1 != password2:
                self.add_error("password2", "تکرار رمز عبور با رمز عبور اولیه یکسان نیست.")
            elif password1:
                candidate_user = get_user_model()(
                    username=cleaned_data.get("username", ""),
                    first_name=cleaned_data.get("first_name", ""),
                    last_name=cleaned_data.get("last_name", ""),
                    email=cleaned_data.get("email", ""),
                )
                try:
                    password_validation.validate_password(password1, candidate_user)
                except ValidationError as error:
                    self.add_error("password1", error)

        return cleaned_data


class StaffPasswordResetForm(forms.Form):
    new_password1 = forms.CharField(
        label="رمز عبور جدید",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "backoffice-input",
                "autocomplete": "new-password",
                "dir": "ltr",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="تکرار رمز عبور جدید",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "backoffice-input",
                "autocomplete": "new-password",
                "dir": "ltr",
            }
        ),
    )

    def __init__(self, *args, staff_user, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff_user = staff_user

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("new_password1")
        password2 = cleaned_data.get("new_password2")

        if password1 and password2 and password1 != password2:
            self.add_error("new_password2", "تکرار رمز عبور با رمز عبور جدید یکسان نیست.")
        elif password1:
            try:
                password_validation.validate_password(password1, self.staff_user)
            except ValidationError as error:
                self.add_error("new_password1", error)

        return cleaned_data


class StaffStatusChangeForm(forms.Form):
    reason = forms.CharField(
        label="یادداشت مدیریتی",
        max_length=1000,
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "backoffice-textarea",
                "rows": 4,
                "placeholder": "مثلاً پایان همکاری یا غیرفعال‌سازی موقت حساب",
            }
        ),
    )
    confirm_change = forms.BooleanField(
        label="اثر این تغییر را بررسی کرده‌ام و آن را تأیید می‌کنم.",
        widget=forms.CheckboxInput(attrs={"class": "backoffice-checkbox"}),
        error_messages={"required": "برای ادامه باید تغییر وضعیت را تأیید کنید."},
    )


class StaffTelegramRevokeForm(forms.Form):
    reason = forms.CharField(
        label="دلیل لغو اتصال Telegram",
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "class": "backoffice-textarea",
                "rows": 3,
                "placeholder": "مثلاً تعویض حساب Telegram یا پایان همکاری",
            }
        ),
        error_messages={"required": "ثبت دلیل لغو اتصال الزامی است."},
    )
