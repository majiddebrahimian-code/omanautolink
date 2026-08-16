from django.urls import path

from . import views


app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("contact/", views.contact, name="contact"),
    # StaticPage.slug also supports Unicode, so do not reject Persian URLs at
    # the routing layer.
    path("<str:slug>/", views.static_page, name="static_page"),
]
