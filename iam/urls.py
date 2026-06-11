from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView, TemplateView
from oauth2_provider.urls import base_urlpatterns, oidc_urlpatterns
from users.views import (
    ApplicationDelete,
    ApplicationDetail,
    ApplicationRegistration,
    ApplicationSecretRegenerate,
    ApplicationUpdate,
    AuthorizationView,
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
    path("accounts/", include("allauth.urls")),
]
