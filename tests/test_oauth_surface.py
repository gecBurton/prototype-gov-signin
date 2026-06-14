"""Trimmed OAuth/OIDC surface.

Covers two hardening changes:
  #6 — the discovery document advertises only what the server honours
       (code grant, RS256, S256), and weak PKCE (plain) is rejected;
  #7 — surplus endpoints (the unusable device-authorization grant, the
       dead password-reset flow) are removed.
"""

import json

import pytest
from django.contrib.auth import get_user_model

from oauth2_provider.models import get_application_model

from tests.conftest import REDIRECT_URI, authorize_params
from users.models import Team

User = get_user_model()
Application = get_application_model()


# ---------------------------------------------------------------------------
# #6 — discovery document reflects what the server actually honours
# ---------------------------------------------------------------------------


@pytest.fixture
def discovery(client, db):
    response = client.get("/o/.well-known/openid-configuration/")
    assert response.status_code == 200
    return json.loads(response.content)


@pytest.mark.parametrize(
    "field,expected",
    [
        ("response_types_supported", ["code"]),
        ("id_token_signing_alg_values_supported", ["RS256"]),
        ("code_challenge_methods_supported", ["S256"]),
    ],
)
def test_discovery_advertises_only_supported_capabilities(discovery, field, expected):
    assert discovery[field] == expected


def test_discovery_keeps_core_endpoints(discovery):
    # Trimming must not drop the essentials.
    for key in (
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "userinfo_endpoint",
        "jwks_uri",
    ):
        assert discovery[key]


# ---------------------------------------------------------------------------
# #6 — only S256 PKCE is accepted (matches what discovery advertises)
# ---------------------------------------------------------------------------


def _authorize_params(method):
    return authorize_params(code_challenge="x" * 43, code_challenge_method=method)


@pytest.mark.parametrize(
    "method,expected_status",
    [
        ("S256", 200),  # consent screen
        ("plain", 400),  # rejected: plain offers no protection
    ],
)
def test_authorize_requires_s256_pkce(client, db, oauth_app, method, expected_status):
    user = User.objects.create_user(email="pkce@example.com")
    client.force_login(user)
    response = client.get("/o/authorize/", _authorize_params(method))
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# PKCE is mandatory for public clients but optional for confidential ones
# (confidential clients are protected by their secret; this admits inherited
# pre-PKCE web apps without weakening public clients). See settings._pkce_required.
# ---------------------------------------------------------------------------


def _authorize_without_pkce(client_id):
    return {
        "client_id": client_id,
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": REDIRECT_URI,
    }


@pytest.mark.parametrize(
    "client_type,pkce_enforced",
    [
        (Application.CLIENT_CONFIDENTIAL, False),  # secret protects it: PKCE optional
        (Application.CLIENT_PUBLIC, True),  # no secret: PKCE still mandatory
    ],
)
def test_pkce_required_only_for_public_clients(client, db, client_type, pkce_enforced):
    team = Team.objects.create(name=f"PKCE {client_type}")
    team.allowed_email_domains.create(domain="example.com")
    app = Application.objects.create(
        name=f"PKCE {client_type}",
        client_type=client_type,
        redirect_uris=REDIRECT_URI,
        team=team,
    )
    user = User.objects.create_user(email=f"pkce-{client_type}@example.com")
    client.force_login(user)

    response = client.get("/o/authorize/", _authorize_without_pkce(app.client_id))

    if pkce_enforced:
        # Missing PKCE is rejected back to the client, not shown a consent screen.
        assert response.status_code == 302
        assert "error=invalid_request" in response["Location"]
        assert "Code+challenge+required" in response["Location"]
    else:
        assert response.status_code == 200  # consent screen shown


# ---------------------------------------------------------------------------
# #7 — surplus endpoints are gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/o/device-authorization/",
        "/o/device/",
    ],
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_device_grant_endpoints_removed(client, db, path, method):
    assert getattr(client, method)(path).status_code == 404


def test_password_reset_entry_closed(client, db):
    response = client.get("/accounts/password/reset/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


# ---------------------------------------------------------------------------
# RP-initiated logout (end_session_endpoint)
# ---------------------------------------------------------------------------


def test_discovery_advertises_end_session_endpoint(discovery):
    assert discovery["end_session_endpoint"].endswith("/o/logout/")


def test_logout_endpoint_shows_confirmation(client, db):
    # Previously this returned 500 (the feature was routed but disabled).
    user = User.objects.create_user(email="confirm@example.com")
    client.force_login(user)
    response = client.get("/o/logout/")
    assert response.status_code == 200
    assert b"Sign out" in response.content


def test_logout_confirmation_ends_the_session(client, db):
    user = User.objects.create_user(email="logout@example.com")
    client.force_login(user)
    assert "_auth_user_id" in client.session

    response = client.post("/o/logout/", {"allow": "Logout"})

    assert response.status_code == 302  # back to the home page
    assert "_auth_user_id" not in client.session
