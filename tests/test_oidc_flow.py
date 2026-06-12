import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest

from tests.conftest import (
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    authorize_params,
    login_code,
    pkce_pair,
)


@pytest.mark.django_db
def test_full_oidc_authorization_code_flow(client, demo_user, oauth_app, mailoutbox):
    code_verifier, code_challenge = pkce_pair()
    params = authorize_params(
        scope="openid profile email", code_challenge=code_challenge
    )

    # 1. Unauthenticated user hits /o/authorize/ — bounced to login
    response = client.get("/o/authorize/", params)
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]

    # 2. User requests a login code by email
    response = client.post("/accounts/login/code/", {"email": demo_user.email})
    assert response.status_code == 302
    assert len(mailoutbox) == 1

    # 3. User submits the emailed code — now authenticated
    response = client.post(
        "/accounts/login/code/confirm/", {"code": login_code(mailoutbox)}
    )
    assert response.status_code == 302

    # 4. Authenticated user reaches the consent screen
    response = client.get("/o/authorize/", params)
    assert response.status_code == 200

    # 5. User approves — server issues an auth code
    response = client.post("/o/authorize/", {**params, "allow": "Authorize"})
    assert response.status_code == 302
    auth_code = parse_qs(urlparse(response["Location"]).query).get("code", [None])[0]
    assert auth_code, "No auth code in redirect"

    # 6. Client exchanges auth code for tokens
    response = client.post(
        "/o/token/",
        {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code_verifier": code_verifier,
        },
    )
    assert response.status_code == 200
    tokens = json.loads(response.content)
    assert "access_token" in tokens
    assert "id_token" in tokens
    # Access tokens are deliberately short-lived (not the multi-hour default) so
    # access does not long outlive a change in authorization.
    assert tokens["expires_in"] <= 600

    # 7. Client calls userinfo with the access token
    response = client.get(
        "/o/userinfo/",
        HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}",
    )
    assert response.status_code == 200
    userinfo = json.loads(response.content)
    assert "sub" in userinfo

    # 8. ID token contains expected claims
    payload = tokens["id_token"].split(".")[1]
    payload += "=" * (4 - len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    assert claims["aud"] == CLIENT_ID
    assert claims["sub"] == str(demo_user.pk)
    assert "iss" in claims
    # The login-by-code flow proves mailbox control, so the verified claim the
    # relying party trusts must be True for this legitimate path.
    assert claims["email"] == demo_user.email
    assert claims["email_verified"] is True
