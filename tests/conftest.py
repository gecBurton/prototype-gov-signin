import re
import uuid

import pytest
import requests_mock as requests_mock_lib
from django.conf import settings
from django.contrib.auth import get_user_model
from users.models import Team

CLIENT_ID = "demo-client-id"
CLIENT_SECRET = "demo-client-secret"
REDIRECT_URI = "http://localhost/callback"


# ---------------------------------------------------------------------------
# Fake Hydra admin API
#
# There is no Django model for OAuth applications any more (see
# users.hydra): every application is a client registered in Ory Hydra. Rather
# than running a real Hydra instance for the unit test suite, this fakes just
# enough of its admin API in memory — client CRUD, and the login/consent/
# logout challenge flows — for users.hydra's HTTP calls to work against.
# Integration tests (integration_tests/) exercise the real thing.
# ---------------------------------------------------------------------------


class FakeHydra:
    """An in-memory stand-in for Hydra's admin API, registered on a requests_mock adapter."""

    def __init__(self):
        self.clients = {}
        self.login_requests = {}
        self.consent_requests = {}
        self.logout_requests = {}
        # (subject, client_id) pairs that revoke_consent has been called for.
        self.revoked_consents = set()
        # Challenges passed to accept_logout/reject_logout, in call order.
        self.accepted_logout_challenges = []
        self.rejected_logout_challenges = []

    # -- clients ------------------------------------------------------------

    def create_client(self, payload):
        client_id = payload.get("client_id") or str(uuid.uuid4())
        record = {
            "client_id": client_id,
            "client_name": payload.get("client_name", ""),
            "owner": payload.get("owner", ""),
            "redirect_uris": payload.get("redirect_uris") or [],
            "post_logout_redirect_uris": payload.get("post_logout_redirect_uris") or [],
            "allowed_cors_origins": payload.get("allowed_cors_origins") or [],
            "grant_types": payload.get("grant_types") or ["authorization_code"],
            "response_types": payload.get("response_types") or ["code"],
            "scope": payload.get("scope", "openid"),
            "token_endpoint_auth_method": payload.get(
                "token_endpoint_auth_method", "client_secret_post"
            ),
            "skip_consent": payload.get("skip_consent", False),
            "metadata": payload.get("metadata") or {},
            "client_secret": payload.get("client_secret") or uuid.uuid4().hex,
        }
        self.clients[client_id] = record
        return dict(record)

    def get_client(self, client_id):
        record = self.clients.get(client_id)
        if record is None:
            return None
        # client_secret is only ever returned on create/PATCH-secret, never on
        # a plain read — matches Hydra's real behaviour and the "shown once" UI.
        data = dict(record)
        data.pop("client_secret", None)
        return data

    def put_client(self, client_id, payload):
        if client_id not in self.clients:
            return None
        record = self.clients[client_id]
        record.update(
            {
                "client_name": payload.get("client_name", record["client_name"]),
                "owner": payload.get("owner", record["owner"]),
                "redirect_uris": payload.get("redirect_uris", record["redirect_uris"]),
                "post_logout_redirect_uris": payload.get(
                    "post_logout_redirect_uris", record["post_logout_redirect_uris"]
                ),
                "allowed_cors_origins": payload.get(
                    "allowed_cors_origins", record["allowed_cors_origins"]
                ),
                "skip_consent": payload.get("skip_consent", record["skip_consent"]),
                "metadata": payload.get("metadata", record["metadata"]),
            }
        )
        return dict(record)

    def patch_client_secret(self, client_id, new_secret):
        record = self.clients.get(client_id)
        if record is None:
            return None
        record["client_secret"] = new_secret
        return dict(record)

    def delete_client(self, client_id):
        self.clients.pop(client_id, None)

    def list_clients(self):
        return [self.get_client(cid) for cid in self.clients]

    # -- login/consent/logout challenges ------------------------------------

    def start_login(self, client_id):
        challenge = str(uuid.uuid4())
        self.login_requests[challenge] = {
            "challenge": challenge,
            "client": self.get_client(client_id),
            "requested_scope": ["openid"],
            "skip": False,
        }
        return challenge

    def start_consent(self, client_id):
        challenge = str(uuid.uuid4())
        self.consent_requests[challenge] = {
            "challenge": challenge,
            "client": self.get_client(client_id),
            "requested_scope": ["openid"],
            "skip": False,
        }
        return challenge


@pytest.fixture(autouse=True)
def fake_hydra(request):
    hydra = FakeHydra()
    admin_base = "http://hydra-admin.test"

    with requests_mock_lib.Mocker() as m:

        def _clients_post(req, ctx):
            record = hydra.create_client(req.json())
            ctx.status_code = 201
            return record

        def _clients_get(req, ctx):
            client_id = req.path.rsplit("/", 1)[-1]
            record = hydra.get_client(client_id)
            if record is None:
                ctx.status_code = 404
                return {"error": "not found"}
            return record

        def _clients_put(req, ctx):
            client_id = req.path.rsplit("/", 1)[-1]
            record = hydra.put_client(client_id, req.json())
            if record is None:
                ctx.status_code = 404
                return {"error": "not found"}
            return record

        def _clients_patch(req, ctx):
            client_id = req.path.rsplit("/", 1)[-1]
            ops = req.json()
            secret = None
            for op in ops:
                if op.get("path") == "/client_secret":
                    secret = op.get("value")
            record = hydra.patch_client_secret(client_id, secret)
            if record is None:
                ctx.status_code = 404
                return {"error": "not found"}
            return record

        def _clients_delete(req, ctx):
            client_id = req.path.rsplit("/", 1)[-1]
            hydra.delete_client(client_id)
            ctx.status_code = 204
            return None

        def _clients_list(req, ctx):
            return hydra.list_clients()

        def _login_get(req, ctx):
            challenge = req.qs.get("login_challenge", [""])[0]
            record = hydra.login_requests.get(challenge)
            if record is None:
                ctx.status_code = 404
                return {"error": "not found"}
            return record

        def _login_accept(req, ctx):
            challenge = req.qs.get("login_challenge", [""])[0]
            return {
                "redirect_to": (
                    f"{admin_base}/fake-continue?flow=login&challenge={challenge}"
                )
            }

        def _consent_get(req, ctx):
            challenge = req.qs.get("consent_challenge", [""])[0]
            record = hydra.consent_requests.get(challenge)
            if record is None:
                ctx.status_code = 404
                return {"error": "not found"}
            return record

        def _consent_accept(req, ctx):
            challenge = req.qs.get("consent_challenge", [""])[0]
            return {
                "redirect_to": (
                    f"{admin_base}/fake-continue?flow=consent&challenge={challenge}"
                )
            }

        def _consent_reject(req, ctx):
            challenge = req.qs.get("consent_challenge", [""])[0]
            return {
                "redirect_to": (
                    f"{admin_base}/fake-denied?flow=consent&challenge={challenge}"
                )
            }

        def _revoke_consent(req, ctx):
            subject = req.qs.get("subject", [""])[0]
            client_id = req.qs.get("client", [""])[0]
            hydra.revoked_consents.add((subject, client_id))
            ctx.status_code = 204
            return None

        def _logout_accept(req, ctx):
            challenge = req.qs.get("logout_challenge", [""])[0]
            hydra.accepted_logout_challenges.append(challenge)
            return {
                "redirect_to": f"{admin_base}/fake-continue?flow=logout&challenge={challenge}"
            }

        def _logout_reject(req, ctx):
            challenge = req.qs.get("logout_challenge", [""])[0]
            hydra.rejected_logout_challenges.append(challenge)
            return {
                "redirect_to": f"{admin_base}/fake-denied?flow=logout&challenge={challenge}"
            }

        m.post(f"{admin_base}/admin/clients", json=_clients_post)
        m.get(re.compile(rf"^{admin_base}/admin/clients(\?.*)?$"), json=_clients_list)
        m.get(re.compile(rf"^{admin_base}/admin/clients/[^/?]+$"), json=_clients_get)
        m.put(re.compile(rf"^{admin_base}/admin/clients/[^/?]+$"), json=_clients_put)
        m.patch(
            re.compile(rf"^{admin_base}/admin/clients/[^/?]+$"), json=_clients_patch
        )
        m.delete(
            re.compile(rf"^{admin_base}/admin/clients/[^/?]+$"), json=_clients_delete
        )
        m.get(f"{admin_base}/admin/oauth2/auth/requests/login", json=_login_get)
        m.put(
            f"{admin_base}/admin/oauth2/auth/requests/login/accept",
            json=_login_accept,
        )
        m.get(f"{admin_base}/admin/oauth2/auth/requests/consent", json=_consent_get)
        m.put(
            f"{admin_base}/admin/oauth2/auth/requests/consent/accept",
            json=_consent_accept,
        )
        m.put(
            f"{admin_base}/admin/oauth2/auth/requests/consent/reject",
            json=_consent_reject,
        )
        m.put(
            f"{admin_base}/admin/oauth2/auth/requests/logout/accept",
            json=_logout_accept,
        )
        m.put(
            f"{admin_base}/admin/oauth2/auth/requests/logout/reject",
            json=_logout_reject,
        )
        m.delete(
            f"{admin_base}/admin/oauth2/auth/sessions/consent",
            json=_revoke_consent,
        )

        settings.HYDRA_ADMIN_URL = admin_base
        hydra.admin_base = admin_base
        yield hydra


def make_hydra_application(fake_hydra, team, **overrides):
    """Create a fake Hydra client and return a users.hydra.Application for it."""
    from users import hydra as hydra_module

    kwargs = {
        "name": "Test App",
        "redirect_uris": ["http://localhost/callback"],
        "team_id": team.pk,
    }
    kwargs.update(overrides)
    return hydra_module.create_application(**kwargs)


# ---------------------------------------------------------------------------
# Shared OIDC-flow helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def configure_settings():
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ALLOWED_HOSTS = ["testserver", "localhost"]


def login_code(mailoutbox):
    """Extract the allauth login-by-code from the most recent email."""
    import re as _re

    return _re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mailoutbox[-1].body).group(1)


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
def app(fake_hydra, owner, team):
    return make_hydra_application(fake_hydra, team, name="Test App")


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
def make_application(fake_hydra):
    def _make(team, **kwargs):
        return make_hydra_application(fake_hydra, team, **kwargs)

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
