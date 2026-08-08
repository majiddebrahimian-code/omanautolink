"""Forms for the typed, editor-managed public-site configuration."""

from django import forms

from .models import (
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


class PanelModelForm(forms.ModelForm):
    """Keep form markup consistent with the custom RTL backoffice."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            current_class = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = f"{current_class} panel-checkbox".strip()
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = f"{current_class} backoffice-select".strip()
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs["class"] = f"{current_class} backoffice-file-input".strip()
            else:
                widget.attrs["class"] = f"{current_class} backoffice-input".strip()


class SiteIdentityForm(PanelModelForm):
    class Meta:
        model = SiteConfiguration
        fields = (
            "site_name", "legal_name", "tagline",
            "logo_light", "logo_dark", "favicon",
            "primary_color", "accent_color", "surface_color",
            "support_phone", "support_email", "telegram_url", "address",
            "copyright_text",
        )
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class SeoConfigurationForm(PanelModelForm):
    class Meta:
        model = SeoConfiguration
        fields = (
            "default_meta_title", "default_meta_description", "default_meta_keywords",
            "default_robots", "google_site_verification", "bing_site_verification",
            "twitter_handle", "default_og_image",
        )
        widgets = {
            "default_meta_description": forms.Textarea(attrs={"rows": 3}),
            "default_meta_keywords": forms.Textarea(attrs={"rows": 2}),
        }


class HomePageConfigurationForm(PanelModelForm):
    class Meta:
        model = HomePageConfiguration
        exclude = ("site_configuration",)
        widgets = {
            "hero_description": forms.Textarea(attrs={"rows": 4}),
            "tracking_section_description": forms.Textarea(attrs={"rows": 3}),
        }


class HeaderNavigationItemForm(PanelModelForm):
    class Meta:
        model = HeaderNavigationItem
        fields = "__all__"


class FooterSectionForm(PanelModelForm):
    class Meta:
        model = FooterSection
        fields = "__all__"


class FooterLinkForm(PanelModelForm):
    class Meta:
        model = FooterLink
        fields = "__all__"


class SocialLinkForm(PanelModelForm):
    class Meta:
        model = SocialLink
        fields = "__all__"


class HomeFeatureCardForm(PanelModelForm):
    class Meta:
        model = HomeFeatureCard
        exclude = ("home_page",)
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class HomeQuickActionForm(PanelModelForm):
    class Meta:
        model = HomeQuickAction
        exclude = ("home_page",)


class StaticPageForm(PanelModelForm):
    class Meta:
        model = StaticPage
        fields = "__all__"
        widgets = {
            "intro": forms.Textarea(attrs={"rows": 3}),
            "body": forms.Textarea(attrs={"rows": 12}),
            "meta_description": forms.Textarea(attrs={"rows": 3}),
            "meta_keywords": forms.Textarea(attrs={"rows": 2}),
        }
