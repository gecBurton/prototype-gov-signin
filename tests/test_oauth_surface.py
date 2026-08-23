"""Trimmed OAuth/OIDC surface.

Covers:
  #6 — the discovery document (proxied from Hydra, see
       users.views.DiscoveryInfoView) advertises only what this app actually
       supports on top of Hydra (code grant, S256 PKCE);
  #7 — weak PKCE (plain) is rejected at the login-challenge step, before this
       app ever accepts the login request Hydra is waiting on;
  RP-initiated logout — the logout-challenge view shows a confirmation page
  and defers to Hydra's own logout accept/reject.

Discovery tests need a live Hydra to proxy against (DiscoveryInfoView makes a
real HTTP call to HYDRA_PUBLIC_URL), so they are marked to skip when Hydra
isn't reachable — covered for real in integration_tests/.
"""

import pytest
import requests
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


def _hydra_reachable():
    try:
        requests.get(
            f"{settings.HYDRA_PUBLIC_URL}/.well-known/openid-configuration", timeout=1
        )
        return True
    except requests.RequestException:
        return False


requires_hydra = pytest.mark.skipif(
    not _hydra_reachable(), reason="Ory Hydra is not reachable from the test runner"
)


# ---------------------------------------------------------------------------
# #6 — discovery document reflects what this app actually honours
# ---------------------------------------------------------------------------


@pytest.fixture
def discovery(client, db):
    import json

    if not _hydra_reachable():
        pytest.skip("Ory Hydra is not reachable from the test runner")

    response = client.get("/o/.well-known/openid-configuration")
    assert response.status_code == 200
    return json.loads(response.content)


@requires_hydra
def test_discovery_advertises_only_supported_capabilities(discovery):
    assert discovery["response_types_supported"] == ["code"]
    assert discovery["code_challenge_methods_supported"] == ["S256"]


@requires_hydra
def test_discovery_keeps_core_endpoints(discovery):
    for key in (
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "userinfo_endpoint",
        "jwks_uri",
    ):
        assert discovery[key]


# ---------------------------------------------------------------------------
# #7 — only S256 PKCE is accepted at the login-challenge step
# ---------------------------------------------------------------------------


def _login_request_with_pkce(fake_hydra, client_id, method):
    challenge = fake_hydra.start_login(client_id)
    fake_hydra.login_requests[challenge]["request_url"] = (
        f"http://hydra/oauth2/auth?client_id={client_id}"
        f"&code_challenge=x{'x' * 42}&code_challenge_method={method}"
    )
    return challenge


@pytest.mark.parametrize(
    "method,expected_status",
    [
        ("S256", 302),  # login accepted, redirected back into Hydra
        ("plain", 400),  # rejected: plain offers no protection
    ],
)
def test_login_requires_s256_pkce(
    client,
    fake_hydra,
    allowed_user,
    make_team,
    make_application,
    method,
    expected_status,
):
    app = make_application(make_team("T", domains=["allowed.com"]))
    client.force_login(allowed_user)
    challenge = _login_request_with_pkce(fake_hydra, app.client_id, method)
    response = client.get(f"/o/login/?login_challenge={challenge}")
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# RP-initiated logout
# ---------------------------------------------------------------------------


def test_logout_endpoint_shows_confirmation(client, db):
    response = client.get("/o/logout/?logout_challenge=some-challenge")
    assert response.status_code == 200
    assert b"Sign out" in response.content


def test_logout_missing_challenge_is_bad_request(client, db):
    assert client.get("/o/logout/").status_code == 400
