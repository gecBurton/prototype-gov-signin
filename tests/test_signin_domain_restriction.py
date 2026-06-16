"""Global sign-in domain allow-list.

Whether an email may sign in to the IdP *at all* is gated by the union of every
team's allowed email domains: an address is admitted if some team would admit
its domain. The gate runs on both sign-in paths — the login-by-code form and
Google — so neither can bypass the other. It is applied ahead of the finer
per-application domain check at the authorize endpoint.
"""

import pytest
from allauth.account.models import EmailAddress
from allauth.core import context
from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import Client, RequestFactory
from users.domains import is_signin_domain_allowed
from users.models import AllowedEmailDomain

User = get_user_model()

GOOGLE_UID = "115147437611111111111"


@pytest.fixture
def team_with_domain(make_team):
    """A team allowing a non-government domain, so the per-team union path can be
    tested distinctly from the blanket .gov.uk rule."""
    return make_team("Vendor", domains=["contractor.example"])


# --- the matcher -------------------------------------------------------------


@pytest.mark.parametrize(
    "email, allowed",
    [
        # Blanket .gov.uk rule (no team needed)
        ("alice@cabinetoffice.gov.uk", True),
        ("bob@digital.service.gov.uk", True),
        ("clerk@gov.uk", True),
        # Look-alikes that are not .gov.uk on a label boundary
        ("eve@notgov.uk", False),
        ("mallory@gmail.com", False),
        # Admitted via a team's allowed domain
        ("dev@contractor.example", True),
    ],
)
def test_is_signin_domain_allowed(team_with_domain, email, allowed):
    assert is_signin_domain_allowed(email) is allowed


def test_admins_always_allowed(db, settings):
    # Escape hatch: an admin on an outside domain can still sign in — this is
    # what lets the first admin bootstrap the allow-list on a fresh instance.
    settings.ADMIN_USERS = ["boss@outside.example"]
    assert is_signin_domain_allowed("boss@outside.example") is True
    assert is_signin_domain_allowed("BOSS@OUTSIDE.EXAMPLE") is True  # case-insensitive
    # A non-admin on the same outside domain is still refused.
    assert is_signin_domain_allowed("other@outside.example") is False


def test_fail_closed_when_no_team_domains(db, settings):
    # No empty-union "allow all": with no team domains and not gov.uk/admin, an
    # address is refused. Bootstrap is via the admin/.gov.uk escapes instead.
    # Delete within this (rolled-back) test so session-scoped fixtures that
    # seeded a domain elsewhere don't interfere.
    AllowedEmailDomain.objects.all().delete()
    settings.ADMIN_USERS = None
    assert is_signin_domain_allowed("anyone@anywhere.example") is False


# --- login-by-code path ------------------------------------------------------


@pytest.mark.parametrize(
    "email, allowed",
    [
        ("alice@cabinetoffice.gov.uk", True),
        ("mallory@gmail.com", False),
    ],
)
def test_login_code_enforces_domain(team_with_domain, mailoutbox, email, allowed):
    response = Client().post("/accounts/login/code/", {"email": email})

    # Allowed → account created and a code emailed; refused → neither, and the
    # form is re-rendered with the error rather than redirecting to confirm.
    assert User.objects.filter(email=email).exists() is allowed
    assert (len(mailoutbox) == 1) is allowed
    assert response.status_code == (302 if allowed else 200)


# --- Google path -------------------------------------------------------------


@pytest.fixture
def social_request(db):
    request = RequestFactory().get("/accounts/google/login/callback/")
    SessionMiddleware(lambda r: None).process_request(request)
    MessageMiddleware(lambda r: None).process_request(request)
    request.user = AnonymousUser()
    return request


def _google_login(request, email):
    provider = get_social_adapter().get_provider(request, "google")
    sociallogin = SocialLogin(
        user=User(email=email),
        account=SocialAccount(provider="google", uid=GOOGLE_UID),
        email_addresses=[EmailAddress(email=email, verified=True, primary=True)],
        provider=provider,
    )
    sociallogin.state = {"process": "login"}
    with context.request_context(request):
        return complete_social_login(request, sociallogin)


@pytest.mark.parametrize(
    "email, allowed",
    [
        ("alice@cabinetoffice.gov.uk", True),
        ("mallory@gmail.com", False),
    ],
)
def test_google_login_enforces_domain(social_request, team_with_domain, email, allowed):
    response = _google_login(social_request, email)

    assert User.objects.filter(email=email).exists() is allowed
    if allowed:
        user = User.objects.get(email=email)
        assert social_request.session["_auth_user_id"] == str(user.pk)
    else:
        # Refused before any account is created; bounced back to the login page.
        assert response.status_code == 302
        assert "_auth_user_id" not in social_request.session
