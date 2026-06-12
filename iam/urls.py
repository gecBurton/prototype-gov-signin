from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView, TemplateView
from oauth2_provider.urls import base_urlpatterns, oidc_urlpatterns
from users.views import (
    ApplicationDelete,
    ApplicationDetail,
    ApplicationRegistration,
    ApplicationSecretRegenerate,
    ApplicationUpdate,
    AuthorizationView,
    DiscoveryInfoView,
    TeamDetail,
    TeamDomainAdd,
    TeamDomainRemove,
    TeamList,
    TeamMemberRemove,
)

management_urlpatterns = [
    path("teams/", TeamList.as_view(), name="teams"),
    path("teams/<uuid:pk>/", TeamDetail.as_view(), name="team"),
    path(
        "teams/<uuid:pk>/members/<uuid:user_pk>/remove/",
        TeamMemberRemove.as_view(),
        name="remove-team-member",
    ),
    path("teams/<uuid:pk>/domains/", TeamDomainAdd.as_view(), name="add-domain"),
    path(
        "teams/<uuid:pk>/domains/<uuid:domain_pk>/remove/",
        TeamDomainRemove.as_view(),
        name="remove-domain",
    ),
    path(
        "teams/<uuid:team_pk>/applications/register/",
        ApplicationRegistration.as_view(),
        name="register",
    ),
    path(
        "teams/<uuid:team_pk>/applications/<uuid:pk>/",
        ApplicationDetail.as_view(),
        name="detail",
    ),
    path(
        "teams/<uuid:team_pk>/applications/<uuid:pk>/update/",
        ApplicationUpdate.as_view(),
        name="update",
    ),
    path(
        "teams/<uuid:team_pk>/applications/<uuid:pk>/delete/",
        ApplicationDelete.as_view(),
        name="delete",
    ),
    path(
        "teams/<uuid:team_pk>/applications/<uuid:pk>/regenerate-secret/",
        ApplicationSecretRegenerate.as_view(),
        name="regenerate-secret",
    ),
]

authorize_urlpatterns = [
    path("authorize/", AuthorizationView.as_view(), name="authorize"),
]

# Drop endpoints the server cannot honour:
#  - authorize/ is replaced by our domain-checking AuthorizationView above;
#  - the device-authorization grant is unusable (every Application is
#    constrained to the authorization-code grant), so don't expose its
#    endpoints at all.
_DROPPED_BASE_NAMES = {
    "authorize",
    "device-authorization",
    "device",
    "device-confirm",
    "device-grant-status",
}
filtered_base_urlpatterns = [
    p for p in base_urlpatterns if p.name not in _DROPPED_BASE_NAMES
]

# Replace the toolkit's discovery document with one that advertises only what
# we honour (RS256 / S256 / code); see DiscoveryInfoView.
discovery_urlpatterns = [
    re_path(
        r"^\.well-known/openid-configuration/?$",
        DiscoveryInfoView.as_view(),
        name="oidc-connect-discovery-info",
    ),
]
filtered_oidc_urlpatterns = [
    p for p in oidc_urlpatterns if p.name != "oidc-connect-discovery-info"
]

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
                + discovery_urlpatterns
                + filtered_oidc_urlpatterns,
                "oauth2_provider",
            )
        ),
    ),
    # Close allauth's standalone signup page: accounts are only ever created by
    # the login-by-code auto-enrol flow (users/forms.py) or a verified Google
    # login. The open signup form takes just an email and (before mandatory
    # verification) handed out a session for an unverified address. Shadowing
    # the route here — rather than the account adapter's is_open_for_signup —
    # leaves Google's social auto-signup working. Listed before the allauth
    # include so it wins; covers GET and POST.
    path(
        "accounts/signup/",
        RedirectView.as_view(pattern_name="account_login", permanent=False),
    ),
    # This service has no passwords: accounts authenticate by email code or
    # Google and have unusable passwords. Close allauth's password endpoints so
    # the notion of a password cannot re-enter — reset can't email arbitrary
    # addresses, and change/set can't give an account a usable password. Listed
    # before the allauth include so they win.
    *(
        path(
            f"accounts/password/{action}/",
            RedirectView.as_view(pattern_name="account_login", permanent=False),
        )
        for action in ("reset", "change", "set")
    ),
    path("accounts/", include("allauth.urls")),
]
