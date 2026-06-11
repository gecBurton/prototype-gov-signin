"""Google social login.

Real Google cannot be driven from tests, so these call allauth's
complete_social_login with the SocialLogin a successful Google handshake
would produce: a Google-verified email address and a provider uid.
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
from django.test import RequestFactory

User = get_user_model()

GOOGLE_UID = "115147437611111111111"


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


def test_google_login_links_existing_email_code_account(social_request):
    """A user who previously signed in by email code is not duplicated."""
    email = "existing@example.com"
    existing = User.objects.create_user(email=email)
    EmailAddress.objects.create(user=existing, email=email, primary=True, verified=True)

    response = _google_login(social_request, email)

    assert response.status_code == 302
    assert User.objects.filter(email=email).count() == 1
    assert social_request.session["_auth_user_id"] == str(existing.pk)
    # EMAIL_AUTHENTICATION_AUTO_CONNECT: linked for future logins.
    assert SocialAccount.objects.filter(user=existing, uid=GOOGLE_UID).exists()


def test_google_login_creates_new_user(social_request):
    email = "fresh@example.com"

    response = _google_login(social_request, email)

    assert response.status_code == 302
    user = User.objects.get(email=email)
    assert social_request.session["_auth_user_id"] == str(user.pk)
    assert SocialAccount.objects.filter(user=user, uid=GOOGLE_UID).exists()
    assert EmailAddress.objects.filter(user=user, email=email, verified=True).exists()
