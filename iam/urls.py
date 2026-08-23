from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView, TemplateView
from users.views import (
    ApplicationDelete,
    ApplicationDetail,
    ApplicationDirectory,
    ApplicationRegistration,
    ApplicationSecretRegenerate,
    ApplicationUpdate,
    HydraConsentView,
    HydraLoginView,
    HydraLogoutView,
    SignInLog,
    TeamDetail,
    TeamDomainAdd,
    TeamDomainRemove,
    TeamList,
    TeamMemberRemove,
)

management_urlpatterns = [
    path("applications/", ApplicationDirectory.as_view(), name="applications"),
    path("logs/", SignInLog.as_view(), name="logs"),
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
        "teams/<uuid:team_pk>/applications/<str:pk>/",
        ApplicationDetail.as_view(),
        name="detail",
    ),
    path(
        "teams/<uuid:team_pk>/applications/<str:pk>/update/",
        ApplicationUpdate.as_view(),
        name="update",
    ),
    path(
        "teams/<uuid:team_pk>/applications/<str:pk>/delete/",
        ApplicationDelete.as_view(),
        name="delete",
    ),
    path(
        "teams/<uuid:team_pk>/applications/<str:pk>/regenerate-secret/",
        ApplicationSecretRegenerate.as_view(),
        name="regenerate-secret",
    ),
]

# Hydra delegates login, consent and logout decisions to this app by
# redirecting the user's browser here with a challenge id (see
# HYDRA_ADMIN_URL/URLS_LOGIN/URLS_CONSENT/URLS_LOGOUT in settings and
# docker-compose.yml). These replace django-oauth-toolkit's /o/authorize/.
#
# There is no discovery-document route here: relying parties are configured
# with Hydra's own endpoint URLs directly (see docker-compose.yml's Grafana
# config), and Hydra serves its own /.well-known/openid-configuration.
hydra_urlpatterns = [
    path("login/", HydraLoginView.as_view(), name="hydra-login"),
    path("consent/", HydraConsentView.as_view(), name="hydra-consent"),
    path("logout/", HydraLogoutView.as_view(), name="hydra-logout"),
]

urlpatterns = [
    path("", TemplateView.as_view(template_name="start.html"), name="start"),
    # Django's admin login is the only password form in this service and has no
    # brute-force protection. Shadow it (as with signup/password below) so admin
    # auth goes through allauth's passwordless, rate-limited login; admin access
    # is then "signed in via allauth AND is_staff".
    path(
        "admin/login/",
        # query_string=True carries the admin's ?next= through to allauth so a
        # deep link into the admin survives the sign-in round-trip.
        RedirectView.as_view(
            pattern_name="account_login", permanent=False, query_string=True
        ),
    ),
    path("admin/", admin.site.urls),
    path(
        "o/",
        include((hydra_urlpatterns + management_urlpatterns, "oauth2_provider")),
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
