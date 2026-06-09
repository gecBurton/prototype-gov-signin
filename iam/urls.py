from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from oauth2_provider.urls import base_urlpatterns, oidc_urlpatterns

from users.views import (
    ApplicationDelete,
    ApplicationDetail,
    ApplicationList,
    ApplicationOwnerManage,
    ApplicationOwnerRemove,
    ApplicationRegistration,
    ApplicationUpdate,
    AuthorizationView,
)

management_urlpatterns = [
    path("applications/", ApplicationList.as_view(), name="list"),
    path("applications/register/", ApplicationRegistration.as_view(), name="register"),
    path("applications/<slug:pk>/", ApplicationDetail.as_view(), name="detail"),
    path("applications/<slug:pk>/delete/", ApplicationDelete.as_view(), name="delete"),
    path("applications/<slug:pk>/update/", ApplicationUpdate.as_view(), name="update"),
    path(
        "applications/<slug:pk>/owners/",
        ApplicationOwnerManage.as_view(),
        name="owners",
    ),
    path(
        "applications/<slug:pk>/owners/<int:user_pk>/remove/",
        ApplicationOwnerRemove.as_view(),
        name="remove-owner",
    ),
]

authorize_urlpatterns = [
    path("authorize/", AuthorizationView.as_view(), name="authorize"),
]

# Replace the default authorize/ with our domain-checking view.
filtered_base_urlpatterns = [p for p in base_urlpatterns if p.name != "authorize"]

urlpatterns = [
    path("", TemplateView.as_view(template_name="start.html"), name="start"),
    path("admin/", admin.site.urls),
    path(
        "o/",
        include(
            (
                authorize_urlpatterns
                + filtered_base_urlpatterns
                + management_urlpatterns
                + oidc_urlpatterns,
                "oauth2_provider",
            )
        ),
    ),
    path("accounts/", include("allauth.urls")),
]
