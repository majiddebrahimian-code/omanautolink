from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path(
        "vehicle/",
        views.public_custom_vehicle_request_create,
        name="custom_vehicle_request_create",
    ),
    path(
        "vehicle/success/",
        views.public_custom_vehicle_request_success,
        name="custom_vehicle_request_success",
    ),
]
