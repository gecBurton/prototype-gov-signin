"""Regression tests for the unverified-signup identity-spoofing fix.

Before the fix, allauth's open ``/accounts/signup/`` page (only an email, no
password, no code) plus ``ACCOUNT_EMAIL_VERIFICATION="optional"`` handed an
unauthenticated caller a logged-in session for an address they did not control,
and the consent-accept step then asserted ``email_verified: true`` for it —
letting anyone mint an ID token impersonating any email and bypass the domain
allowlist.

The fix has three parts, covered here:
  1. the standalone signup page is closed (urls.py);
  2. email verification is mandatory, so no unverified session (settings.py);
  3. the ``email_verified`` claim reflects the real EmailAddress state
     (users.hydra.accept_consent).
"""

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model

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
#
# This is now computed in users.hydra.accept_consent (the Hydra-facing
# equivalent of the old OIDCValidator.get_additional_claims), which builds the
# session dict handed to Hydra's consent-accept admin API — Hydra puts that
# straight into the ID token it signs, so asserting on the built session dict
# here is equivalent to asserting on the eventual claim.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verified", [True, False])
def test_email_verified_claim_follows_emailaddress(
    db, fake_hydra, allowed_user, make_team, make_application, verified, monkeypatch
):
    EmailAddress.objects.filter(user=allowed_user).delete()
    EmailAddress.objects.create(
        user=allowed_user, email=allowed_user.email, primary=True, verified=verified
    )
    app = make_application(make_team("T", domains=["allowed.com"]))

    captured = {}
    original_request = __import__("users.hydra", fromlist=["_request"])._request

    def _capture(method, path, **kwargs):
        if path == "/admin/oauth2/auth/requests/consent/accept":
            captured.update(kwargs["json"])
        return original_request(method, path, **kwargs)

    monkeypatch.setattr("users.hydra._request", _capture)

    challenge = fake_hydra.start_consent(app.client_id)
    from django.test import Client

    c = Client()
    c.force_login(allowed_user)
    c.post("/o/consent/", {"consent_challenge": challenge, "allow": "Authorize"})

    assert captured["session"]["id_token"]["email_verified"] is verified


def test_email_verified_false_without_emailaddress(
    db, fake_hydra, allowed_user, make_team, make_application, monkeypatch
):
    """A user with no EmailAddress row must not be reported as verified."""
    EmailAddress.objects.filter(user=allowed_user).delete()
    app = make_application(make_team("T", domains=["allowed.com"]))

    captured = {}
    original_request = __import__("users.hydra", fromlist=["_request"])._request

    def _capture(method, path, **kwargs):
        if path == "/admin/oauth2/auth/requests/consent/accept":
            captured.update(kwargs["json"])
        return original_request(method, path, **kwargs)

    monkeypatch.setattr("users.hydra._request", _capture)

    challenge = fake_hydra.start_consent(app.client_id)
    from django.test import Client

    c = Client()
    c.force_login(allowed_user)
    c.post("/o/consent/", {"consent_challenge": challenge, "allow": "Authorize"})

    assert captured["session"]["id_token"]["email_verified"] is False
