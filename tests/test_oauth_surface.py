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

from tests.conftest import authorize_params

User = get_user_model()


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
