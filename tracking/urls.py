from django.urls import path

from . import views

app_name = "tracking"

urlpatterns = [
    path("", views.public_tracking_lookup, name="public_lookup"),
]
