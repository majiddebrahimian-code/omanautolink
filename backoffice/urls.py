from django.urls import path

from . import views

app_name = "backoffice"

urlpatterns = [
    path("logout/", views.panel_logout, name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("reports/audit-log/", views.audit_log, name="audit_log"),
    path("machines/", views.machine_list, name="machine_list"),
    path("machines/new/", views.machine_create, name="machine_create"),
    path("machines/<int:pk>/edit/", views.machine_edit, name="machine_edit"),
    path(
        "machines/<int:pk>/photos/",
        views.machine_photo_manage,
        name="machine_photo_manage",
    ),
    path(
        "machines/<int:pk>/photos/upload/",
        views.machine_photo_upload,
        name="machine_photo_upload",
    ),
    path(
        "machines/<int:pk>/photos/<int:photo_pk>/update/",
        views.machine_photo_update,
        name="machine_photo_update",
    ),
    path(
        "machines/<int:pk>/photos/<int:photo_pk>/set-cover/",
        views.machine_photo_set_cover,
        name="machine_photo_set_cover",
    ),
    path(
        "machines/<int:pk>/photos/<int:photo_pk>/delete/",
        views.machine_photo_delete,
        name="machine_photo_delete",
    ),
    path(
        "machines/<int:pk>/archive/",
        views.machine_archive,
        name="machine_archive",
    ),
    path(
        "machines/<int:pk>/publish/",
        views.machine_publish,
        name="machine_publish",
    ),
    path(
        "machines/<int:pk>/hold/",
        views.machine_hold_create,
        name="machine_hold_create",
    ),
    path("machines/holds/", views.vehicle_hold_list, name="vehicle_hold_list"),
    path(
        "machines/holds/<int:pk>/release/",
        views.vehicle_hold_release,
        name="vehicle_hold_release",
    ),
    path(
        "machines/holds/<int:pk>/sell/",
        views.vehicle_hold_sale,
        name="vehicle_hold_sale",
    ),
    path(
        "machines/sold/pending-delivery/",
        views.pending_delivery_list,
        name="pending_delivery_list",
    ),
    path(
        "machines/sold/delivered/",
        views.delivered_machine_list,
        name="delivered_machine_list",
    ),
    path(
        "machines/sold/<int:pk>/",
        views.delivery_machine_detail,
        name="delivery_machine_detail",
    ),
    path(
        "customer-requests/",
        views.custom_vehicle_request_list,
        name="custom_vehicle_request_list",
    ),
    path(
        "customer-requests/<int:pk>/",
        views.custom_vehicle_request_detail,
        name="custom_vehicle_request_detail",
    ),
    path(
        "customer-requests/<int:pk>/convert/",
        views.custom_vehicle_request_convert,
        name="custom_vehicle_request_convert",
    ),
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path(
        "clearance/operations/",
        views.clearance_operation,
        name="clearance_operation",
    ),
    path("clearance/queue/", views.clearance_queue, name="clearance_queue"),
    path(
        "clearance/queue/<int:pk>/receive/",
        views.clearance_queue_receive,
        name="clearance_queue_receive",
    ),
    path(
        "clearance/queue/<int:pk>/complete/",
        views.clearance_queue_complete,
        name="clearance_queue_complete",
    ),
    path("clearance/imports/", views.tracking_import_list, name="tracking_import_list"),
    path("clearance/imports/new/", views.tracking_import_create, name="tracking_import_create"),
    path("clearance/imports/<int:pk>/", views.tracking_import_detail, name="tracking_import_detail"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/new/", views.staff_create, name="staff_create"),
    path("staff/roles/", views.staff_role_guide, name="staff_role_guide"),
    path("staff/<int:pk>/", views.staff_detail, name="staff_detail"),
    path("staff/<int:pk>/edit/", views.staff_edit, name="staff_edit"),
    path(
        "staff/<int:pk>/password/",
        views.staff_password_reset,
        name="staff_password_reset",
    ),
    path("staff/<int:pk>/status/", views.staff_status, name="staff_status"),
    path(
        "staff/<int:pk>/telegram/link/",
        views.staff_telegram_link_issue,
        name="staff_telegram_link_issue",
    ),
    path(
        "staff/<int:pk>/telegram/revoke/",
        views.staff_telegram_link_revoke,
        name="staff_telegram_link_revoke",
    ),
    path("blog/new/", views.blog_post_create, name="blog_post_create"),
    path("blog/", views.blog_post_list, name="blog_post_list"),
    path("blog/<int:pk>/edit/", views.blog_post_edit, name="blog_post_edit"),
    path(
        "blog/<int:pk>/publish/",
        views.blog_post_publish,
        name="blog_post_publish",
    ),
    path(
        "blog/<int:pk>/unpublish/",
        views.blog_post_unpublish,
        name="blog_post_unpublish",
    ),
    path("blog/<int:pk>/delete/", views.blog_post_delete, name="blog_post_delete"),
    path("settings/site/", views.site_settings, name="site_settings"),
    path(
        "settings/site/identity/",
        views.site_identity_settings,
        name="site_identity_settings",
    ),
    path(
        "settings/site/homepage/",
        views.site_homepage_settings,
        name="site_homepage_settings",
    ),
    path(
        "settings/site/<slug:collection>/",
        views.site_collection_list,
        name="site_collection_list",
    ),
    path(
        "settings/site/<slug:collection>/new/",
        views.site_collection_create,
        name="site_collection_create",
    ),
    path(
        "settings/site/<slug:collection>/<int:pk>/edit/",
        views.site_collection_edit,
        name="site_collection_edit",
    ),
    path(
        "settings/site/<slug:collection>/<int:pk>/delete/",
        views.site_collection_delete,
        name="site_collection_delete",
    ),
    path(
        "settings/delivery-stages/",
        views.stage_configuration,
        name="stage_configuration",
    ),
    path(
        "settings/delivery-stages/list/",
        views.stage_list,
        name="stage_list",
    ),
    path(
        "settings/delivery-stages/repair-transitions/",
        views.stage_transition_repair,
        name="stage_transition_repair",
    ),
    path(
        "settings/delivery-stages/new/",
        views.stage_create,
        name="stage_create",
    ),
    path(
        "settings/delivery-stages/<int:pk>/edit/",
        views.stage_edit,
        name="stage_edit",
    ),
    path(
        "settings/delivery-stages/<int:pk>/archive/",
        views.stage_archive,
        name="stage_archive",
    ),
]
