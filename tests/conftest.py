import base64
import hashlib
import json
import re
import secrets

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.models import Team

Application = get_application_model()

CLIENT_ID = "demo-client-id"
CLIENT_SECRET = "demo-client-secret"
REDIRECT_URI = "http://localhost/callback"


# ---------------------------------------------------------------------------
# Shared OIDC-flow helpers (used across the authorize/token tests)
# ---------------------------------------------------------------------------


def pkce_pair():
    """Return an S256 ``(code_verifier, code_challenge)`` pair."""
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def authorize_params(
    *,
    client_id=CLIENT_ID,
    scope="openid",
    redirect_uri=REDIRECT_URI,
    code_challenge,
    code_challenge_method="S256",
):
    """Build an ``/o/authorize/`` query dict for the authorization-code flow."""
    return {
        "client_id": client_id,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    }


def login_code(mailoutbox):
    """Extract the allauth login-by-code from the most recent email."""
    return re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mailoutbox[-1].body).group(1)


def authorize_params_for(app, **overrides):
    """Build ``/o/authorize/`` params for a given application with a fresh PKCE pair."""
    _, code_challenge = pkce_pair()
    return authorize_params(
        client_id=app.client_id, code_challenge=code_challenge, **overrides
    )


def exchange_code_for_tokens(client, code, code_verifier):
    """POST an authorization code to the token endpoint and return the response."""
    return client.post(
        "/o/token/",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code_verifier": code_verifier,
        },
    )


def decode_id_token(id_token):
    """Decode a JWT id_token's payload into its claims dict (signature not checked)."""
    payload = id_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@pytest.fixture(autouse=True, scope="session")
def configure_settings():
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ALLOWED_HOSTS = ["testserver", "localhost"]
    if not settings.OAUTH2_PROVIDER.get("OIDC_RSA_PRIVATE_KEY"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        settings.OAUTH2_PROVIDER["OIDC_RSA_PRIVATE_KEY"] = pem


@pytest.fixture(scope="session")
def demo_user(django_db_setup, django_db_blocker):
    User = get_user_model()
    with django_db_blocker.unblock():
        user, _ = User.objects.get_or_create(email="demo@example.com")
        user.set_unusable_password()
        user.save()
    return user


@pytest.fixture(scope="session")
def oauth_app(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        # Every application belongs to a team, and a team admits users only on
        # the domains it lists. These tests sign in @example.com users, so allow
        # that domain.
        team, _ = Team.objects.get_or_create(name="Demo Team")
        team.allowed_email_domains.get_or_create(domain="example.com")
        app, _ = Application.objects.update_or_create(
            client_id=CLIENT_ID,
            defaults={
                "name": "Test Client",
                "client_type": Application.CLIENT_CONFIDENTIAL,
                "redirect_uris": REDIRECT_URI,
                "client_secret": CLIENT_SECRET,
                "skip_authorization": False,
                "team": team,
            },
        )
    return app


# ---------------------------------------------------------------------------
# Shared per-test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def authed_client(request, client, db):
    """Parametrize with a fixture name string to get a logged-in client, or None for anonymous."""
    if request.param:
        client.force_login(request.getfixturevalue(request.param))
    return client


@pytest.fixture
def team(db):
    return Team.objects.create(name="Test Team")


@pytest.fixture
def owner(team):
    User = get_user_model()
    user = User.objects.create_user(email="owner@example.com")
    user.teams.add(team)
    return user


@pytest.fixture
def stranger(db):
    User = get_user_model()
    return User.objects.create_user(email="stranger@example.com")


@pytest.fixture
def app(owner, team):
    return Application.objects.create(
        name="Test App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        redirect_uris="http://localhost/callback",
        team=team,
    )


# ---------------------------------------------------------------------------
# Factories — build teams (optionally with allowed domains) and applications
# without re-declaring the same boilerplate in every test module.
# ---------------------------------------------------------------------------


@pytest.fixture
def make_team(db):
    def _make(name="Test Team", domains=()):
        team = Team.objects.create(name=name)
        for domain in domains:
            team.allowed_email_domains.create(domain=domain)
        return team

    return _make


@pytest.fixture
def make_application(db):
    def _make(team, **kwargs):
        return Application.objects.create(
            **{
                "name": "Test App",
                "client_type": Application.CLIENT_CONFIDENTIAL,
                "redirect_uris": "http://localhost/callback",
                "team": team,
                **kwargs,
            }
        )

    return _make


@pytest.fixture
def other_team_app(make_team, make_application):
    """An application owned by a team the standard ``owner``/``stranger`` aren't in."""
    return make_application(make_team("Other Team"), name="Other App")


@pytest.fixture
def allowed_user(db):
    User = get_user_model()
    return User.objects.create_user(email="user@allowed.com")


@pytest.fixture
def blocked_user(db):
    User = get_user_model()
    return User.objects.create_user(email="user@blocked.com")
