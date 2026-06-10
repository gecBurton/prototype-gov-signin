import base64
import hashlib
import secrets

import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.models import Team
from users.views import _is_domain_allowed

User = get_user_model()
Application = get_application_model()

REDIRECT_URI = "http://localhost/callback"


def _make_team(name, domains):
    team = Team.objects.create(name=name)
    for domain in domains:
        team.allowed_email_domains.create(domain=domain)
    return team


def _make_app(name, team):
    return Application.objects.create(
        name=name,
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris=REDIRECT_URI,
        algorithm="RS256",
        skip_authorization=False,
        team=team,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def allowed_user(db):
    return User.objects.create_user(email="user@allowed.com")


@pytest.fixture
def blocked_user(db):
    return User.objects.create_user(email="user@blocked.com")


@pytest.fixture
def app(db):
    return _make_app("Restricted App", _make_team("Restricted Team", ["allowed.com"]))


@pytest.fixture
def open_app(db):
    return _make_app("Open App", _make_team("Open Team", []))


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
        ([], "anyone@anything.com", True),  # no domains = allow all
        (["allowed.com"], "user@allowed.com", True),
        (["allowed.com"], "user@blocked.com", False),
        (["ALLOWED.COM"], "user@allowed.com", True),  # domains stored lowercase
        (["allowed.com"], "user@ALLOWED.COM", True),  # case-insensitive email
        (["a.com", "b.com", "c.com"], "user@b.com", True),  # multiple domains
        (["a.com", "b.com", "c.com"], "user@d.com", False),
        (["  allowed.com  "], "user@allowed.com", True),  # whitespace tolerance
        (["gov.uk"], "some.one@department.gov.uk", True),  # subdomains match
        (["gov.uk"], "some.one@deep.nested.gov.uk", True),
        (["gov.uk"], "some.one@evilgov.uk", False),  # suffix must be a full label
        (["department.gov.uk"], "some.one@gov.uk", False),  # parent domain no match
    ],
)
def test_is_domain_allowed(db, domains, email, expected):
    team = _make_team("Test Team", domains)
    assert _is_domain_allowed(Application(team=team), email) is expected


def test_teamless_application_allows_all(db):
    assert _is_domain_allowed(Application(), "anyone@anything.com") is True


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
        ("user@alpha.com", ["alpha.com", "beta.com"], 200),
        ("user@beta.com", ["alpha.com", "beta.com"], 200),
        ("user@gamma.com", ["alpha.com", "beta.com"], 403),
        ("user@ALPHA.COM", ["alpha.com"], 200),  # email domain uppercase
        ("user@alpha.com", ["ALPHA.COM"], 200),  # whitelist uppercase
    ],
)
def test_authorize_domain_cases(client, db, email, allowed_domains, expected_status):
    user = User.objects.create_user(email=email)
    application = _make_app("Test", _make_team("Case Team", allowed_domains))
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
