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


from django.urls import reverse

def internal_destination_choices():
    choices=[("/", "صفحهٔ اصلی"),(reverse("cars:vehicle_list"),"خودروهای موجود"),(reverse("tracking:public_lookup"),"رهگیری خودرو"),(reverse("customers:custom_vehicle_request_create"),"درخواست خودروی سفارشی"),(reverse("blog:post_list"),"مجله"),(reverse("core:contact"),"تماس با ما")]
    choices += [(x.get_absolute_url(),f"صفحهٔ ثابت: {x.title}") for x in StaticPage.objects.filter(is_published=True).order_by("title") if x.slug!="contact"]
    return choices

_labels={"site_name":"نام سایت","legal_name":"نام حقوقی شرکت","tagline":"شعار برند","logo_light":"لوگو برای زمینهٔ روشن","logo_dark":"لوگو برای زمینهٔ تیره","favicon":"آیکن مرورگر","support_phone":"شمارهٔ تماس","support_email":"ایمیل پشتیبانی","telegram_url":"لینک Telegram","address":"نشانی","copyright_text":"متن حقوقی پایین سایت","default_meta_title":"عنوان پیش‌فرض سئو","default_meta_description":"توضیح پیش‌فرض سئو","default_meta_keywords":"کلمات کلیدی پیش‌فرض","default_robots":"دستور موتورهای جست‌وجو","google_site_verification":"کد تأیید Google","bing_site_verification":"کد تأیید Bing","twitter_handle":"شناسهٔ X / Twitter","default_og_image":"تصویر اشتراک‌گذاری پیش‌فرض","hero_eyebrow":"متن کوتاه بالای عنوان","hero_title":"عنوان اصلی","hero_description":"توضیح اصلی","hero_background_image":"تصویر پس‌زمینهٔ Hero","hero_mobile_background_image":"تصویر Hero برای موبایل","hero_image_alt":"متن جایگزین تصویر Hero","hero_featured_car":"خودروی ویژهٔ Hero","primary_cta_label":"متن دکمهٔ اصلی","secondary_cta_label":"متن دکمهٔ دوم","featured_vehicles_heading":"عنوان خودروهای منتخب","route_title":"عنوان مسیر واردات","route_origin_label":"مبدأ مسیر","route_destination_label":"مقصد مسیر","route_transport_label":"روش حمل","route_duration_label":"زمان تقریبی مسیر","route_panel_image":"تصویر نقشه / مسیر","tracking_section_heading":"عنوان بخش رهگیری","tracking_section_description":"توضیح بخش رهگیری","label":"عنوان","destination":"صفحهٔ مقصد","aria_label":"عنوان دسترس‌پذیری (اختیاری)","sort_order":"ترتیب نمایش","is_enabled":"نمایش در سایت","open_in_new_tab":"باز شدن در پنجرهٔ جدید","section":"ستون Footer","platform":"شبکهٔ اجتماعی","url":"لینک شبکهٔ اجتماعی","icon":"آیکن","title":"عنوان","description":"توضیح","cta_label":"متن دکمه","action":"نوع دسترسی"}
_old=PanelModelForm.__init__
def _init(self,*a,**kw):
 _old(self,*a,**kw)
 for n,f in self.fields.items():
  if n in _labels:f.label=_labels[n]
PanelModelForm.__init__=_init
SiteIdentityForm._meta.fields=tuple(x for x in SiteIdentityForm._meta.fields if x not in {"primary_color","accent_color","surface_color"})
HomePageConfigurationForm._meta.exclude=tuple(HomePageConfigurationForm._meta.exclude)+("primary_cta_destination","secondary_cta_destination")

class _DestinationSelect:
 destination=forms.ChoiceField(label="صفحهٔ مقصد",choices=(),help_text="فقط یکی از صفحه‌های داخلی فعال سایت را انتخاب کنید.")
 def __init__(self,*a,**kw):
  super().__init__(*a,**kw); c=internal_destination_choices(); cur=getattr(self.instance,"destination","")
  if cur and cur not in {x for x,_ in c}:c.insert(0,(cur,"مقصد فعلی (نیازمند بازبینی)"))
  self.fields["destination"].choices=c
class HeaderNavigationItemForm(_DestinationSelect,PanelModelForm):
 class Meta:model=HeaderNavigationItem;fields=("label","destination","aria_label","sort_order","is_enabled","open_in_new_tab")
class FooterLinkForm(_DestinationSelect,PanelModelForm):
 class Meta:model=FooterLink;fields="__all__"
class HomeFeatureCardForm(_DestinationSelect,PanelModelForm):
 class Meta:model=HomeFeatureCard;exclude=("home_page",)
class HomeQuickActionForm(_DestinationSelect,PanelModelForm):
 class Meta:model=HomeQuickAction;exclude=("home_page",)
class ContactMessageForm(forms.Form):
 full_name=forms.CharField(label="نام و نام خانوادگی",max_length=160);email=forms.EmailField(label="ایمیل");phone=forms.CharField(label="شمارهٔ تلفن",max_length=40);subject=forms.CharField(label="موضوع پیام",max_length=180,required=False);message=forms.CharField(label="متن پیام",widget=forms.Textarea(attrs={"rows":6}));website=forms.CharField(required=False,widget=forms.HiddenInput)
 def __init__(self,*a,**kw):
  super().__init__(*a,**kw)
  for f in self.fields.values():f.widget.attrs["class"]="public-contact-form__input"


def _finalize_public_site_forms():
    for form_class in (SiteIdentityForm,):
        for field_name in ("primary_color","accent_color","surface_color"):
            form_class.base_fields.pop(field_name,None)
    for field_name in ("primary_cta_destination","secondary_cta_destination"):
        HomePageConfigurationForm.base_fields.pop(field_name,None)
    for form_class in (HeaderNavigationItemForm,FooterLinkForm,HomeFeatureCardForm,HomeQuickActionForm):
        original_init=form_class.__init__
        def init(self,*args,__original=original_init,**kwargs):
            __original(self,*args,**kwargs)
            choices=internal_destination_choices()
            current=getattr(self.instance,"destination","")
            if current and current not in {value for value,_ in choices}:choices.insert(0,(current,"مقصد فعلی (نیازمند بازبینی)"))
            self.fields["destination"]=forms.ChoiceField(label="صفحهٔ مقصد",choices=choices,help_text="فقط یکی از صفحه‌های داخلی فعال سایت را انتخاب کنید.",widget=forms.Select(attrs={"class":"backoffice-select"}))
        form_class.__init__=init
_finalize_public_site_forms()
