"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.sitemaps.views import sitemap
from django.shortcuts import redirect
from django.urls import include, path

from core import views as core_views
from core.sitemaps import public_sitemaps


@staff_member_required(login_url="admin:login")
def admin_entry_router(request):
    """Make the custom backoffice the single operational home for all staff."""

    return redirect("backoffice:dashboard")

urlpatterns = [
    path("admin/", admin_entry_router),
    path("admin/", admin.site.urls),
    path("robots.txt", core_views.robots_txt, name="robots_txt"),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": public_sitemaps},
        name="sitemap",
    ),
    path("panel/", include("backoffice.urls")),
    path("cars/", include("cars.urls")),
    path("blog/", include("blog.urls")),
    path("track/", include("tracking.urls")),
    path("requests/", include("customers.urls")),
    path("integrations/", include("integrations.urls")),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
