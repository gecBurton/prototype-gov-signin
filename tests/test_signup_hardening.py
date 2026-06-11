"""Regression tests for the unverified-signup identity-spoofing fix.

Before the fix, allauth's open ``/accounts/signup/`` page (only an email, no
password, no code) plus ``ACCOUNT_EMAIL_VERIFICATION="optional"`` handed an
unauthenticated caller a logged-in session for an address they did not control,
and ``OIDCValidator`` then asserted ``email_verified: true`` for it — letting
anyone mint an ID token impersonating any email and bypass the domain allowlist.

The fix has three parts, covered here:
  1. the standalone signup page is closed (urls.py);
  2. email verification is mandatory, so no unverified session (settings.py);
  3. the ``email_verified`` claim reflects the real EmailAddress state
     (validators.py).
"""

import base64
import hashlib
import json
import secrets
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from validators import OIDCValidator

from tests.conftest import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI

User = get_user_model()


# ---------------------------------------------------------------------------
# 1. The standalone signup page is closed
# ---------------------------------------------------------------------------


def test_signup_page_is_closed(client, db):
    response = client.get("/accounts/signup/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_signup_post_creates_no_account_and_no_session(client, db):
    """The old attack: POST an email you don't own and get a session for it."""
    email = "intruder@cabinetoffice.gov.uk"
    response = client.post("/accounts/signup/", {"email": email})

    # Bounced to login; the signup form is never processed.
    assert response.status_code == 302
    assert not User.objects.filter(email=email).exists()
    assert "_auth_user_id" not in client.session


# ---------------------------------------------------------------------------
# 3. email_verified reflects the real EmailAddress state, not a hardcoded True
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verified", [True, False])
def test_email_verified_claim_follows_emailaddress(db, verified):
    user = User.objects.create_user(email="claim@example.com")
    EmailAddress.objects.create(
        user=user, email=user.email, primary=True, verified=verified
    )
    claims = OIDCValidator().get_additional_claims(SimpleNamespace(user=user))
    assert claims["email_verified"] is verified


def test_email_verified_false_without_emailaddress(db):
    """A user with no EmailAddress row must not be reported as verified."""
    user = User.objects.create_user(email="noaddr@example.com")
    claims = OIDCValidator().get_additional_claims(SimpleNamespace(user=user))
    assert claims["email_verified"] is False


# ---------------------------------------------------------------------------
# End-to-end invariant: an unverified identity can never obtain a token that
# vouches for its email. This drives the real /o/authorize/ and /o/token/
# endpoints, so it guards the whole issuance pipeline — not just the claim
# helper — against any regression that reintroduces a hardcoded "verified".
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_unverified_session_cannot_mint_a_verified_id_token(client, oauth_app):
    """The core invariant the original vulnerability broke.

    A relying party trusts ``email_verified`` to decide the address really is
    the user's. Here the user has a live session but *no* verified
    EmailAddress (as if a session were obtained for an address whose control
    was never proven). The issued ID token must report ``email_verified: false``
    — and must never claim true — so no downstream service is misled into
    treating the attacker as the address owner.
    """
    user = User.objects.create_user(email="unverified@cabinetoffice.gov.uk")
    client.force_login(user)

    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": "openid email",
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

    response = client.post("/o/authorize/", {**params, "allow": "Authorize"})
    assert response.status_code == 302
    code = parse_qs(urlparse(response["Location"]).query)["code"][0]

    response = client.post(
        "/o/token/",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200

    id_token = json.loads(response.content)["id_token"]
    payload = id_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))

    assert claims["email"] == user.email
    assert claims["email_verified"] is False
