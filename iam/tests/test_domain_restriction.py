import base64
import hashlib
import secrets

import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model

from users.views import _is_domain_allowed

User = get_user_model()
Application = get_application_model()

REDIRECT_URI = "http://localhost/callback"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def allowed_user(db):
    return User.objects.create_user(username="allowed", email="user@allowed.com")


@pytest.fixture
def blocked_user(db):
    return User.objects.create_user(username="blocked", email="user@blocked.com")


@pytest.fixture
def app(db):
    application = Application.objects.create(
        name="Restricted App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=REDIRECT_URI,
        allowed_email_domains="allowed.com",
        algorithm="RS256",
        skip_authorization=False,
    )
    return application


@pytest.fixture
def open_app(db):
    return Application.objects.create(
        name="Open App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=REDIRECT_URI,
        allowed_email_domains="",
        algorithm="RS256",
        skip_authorization=False,
    )


def _authorize_params(app):
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return {
        "client_id": app.client_id,
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }


# ---------------------------------------------------------------------------
# Unit tests for the helper function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "domains,email,expected",
    [
        ("", "anyone@anything.com", True),  # blank = allow all
        ("allowed.com", "user@allowed.com", True),
        ("allowed.com", "user@blocked.com", False),
        ("ALLOWED.COM", "user@allowed.com", True),  # case-insensitive domains
        ("allowed.com", "user@ALLOWED.COM", True),  # case-insensitive email
        ("a.com\nb.com\nc.com", "user@b.com", True),  # multiple domains
        ("a.com\nb.com\nc.com", "user@d.com", False),
        ("  allowed.com  ", "user@allowed.com", True),  # whitespace tolerance
    ],
)
def test_is_domain_allowed(db, domains, email, expected):
    app = Application(allowed_email_domains=domains)
    assert _is_domain_allowed(app, email) is expected


# ---------------------------------------------------------------------------
# Authorization view — GET (consent screen)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("allowed_user", 200),
        ("blocked_user", 403),
    ],
)
def test_authorize_get_domain_check(
    request, client, user_fixture, expected_status, app
):
    client.force_login(request.getfixturevalue(user_fixture))
    response = client.get("/o/authorize/", _authorize_params(app))
    assert response.status_code == expected_status


def test_authorize_get_open_app_allows_all(
    client, allowed_user, blocked_user, open_app
):
    params = _authorize_params(open_app)
    for user in (allowed_user, blocked_user):
        client.force_login(user)
        assert client.get("/o/authorize/", params).status_code == 200


def test_authorize_get_unauthenticated_redirects(client, app):
    response = client.get("/o/authorize/", _authorize_params(app))
    assert response.status_code == 302  # redirect to login, no 403


# ---------------------------------------------------------------------------
# Authorization view — POST (form submission)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("allowed_user", 302),  # success → redirect with auth code
        ("blocked_user", 403),
    ],
)
def test_authorize_post_domain_check(
    request, client, user_fixture, expected_status, app
):
    user = request.getfixturevalue(user_fixture)
    client.force_login(user)
    params = _authorize_params(app)
    response = client.post("/o/authorize/", {**params, "allow": "Authorize"})
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# Multi-domain and case-insensitivity via the view
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email,allowed_domains,expected_status",
    [
        ("user@alpha.com", "alpha.com\nbeta.com", 200),
        ("user@beta.com", "alpha.com\nbeta.com", 200),
        ("user@gamma.com", "alpha.com\nbeta.com", 403),
        ("user@ALPHA.COM", "alpha.com", 200),  # email domain uppercase
        ("user@alpha.com", "ALPHA.COM", 200),  # whitelist uppercase
    ],
)
def test_authorize_domain_cases(client, db, email, allowed_domains, expected_status):
    user = User.objects.create_user(username=email, email=email)
    application = Application.objects.create(
        name="Test",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=REDIRECT_URI,
        allowed_email_domains=allowed_domains,
        algorithm="RS256",
        skip_authorization=False,
    )
    client.force_login(user)
    response = client.get("/o/authorize/", _authorize_params(application))
    assert response.status_code == expected_status


def test_authorize_403_shows_app_name(client, blocked_user, app):
    client.force_login(blocked_user)
    response = client.get("/o/authorize/", _authorize_params(app))
    assert response.status_code == 403
    assert app.name in response.content.decode()


def test_authorize_unknown_client_id(client, allowed_user):
    client.force_login(allowed_user)
    params = {
        "client_id": "nonexistent-client-id",
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": "http://localhost/callback",
        "code_challenge": "x" * 43,
        "code_challenge_method": "S256",
    }
    response = client.get("/o/authorize/", params)
    assert response.status_code != 500
