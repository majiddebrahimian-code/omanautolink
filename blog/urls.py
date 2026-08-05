from django.urls import path

from . import views


app_name = "blog"

urlpatterns = [
    path("", views.public_post_list, name="post_list"),
    # ``str`` deliberately accepts Unicode slugs.  Post.slug uses
    # ``allow_unicode=True`` so Persian SEO-friendly addresses must be
    # routable as well as storable.
    path("<str:slug>/", views.public_post_detail, name="post_detail"),
]
