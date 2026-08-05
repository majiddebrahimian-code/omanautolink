from django.urls import path

from . import views


app_name = "cars"

urlpatterns = [
    path("", views.public_vehicle_list, name="vehicle_list"),
    path(
        "<str:slug>-<int:pk>/",
        views.public_vehicle_detail,
        name="vehicle_detail",
    ),
]
