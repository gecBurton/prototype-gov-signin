"""Thin client for Ory Hydra's admin API, plus the Application wrapper.

There is no local Django model for OAuth applications: Hydra's admin API is
the source of truth for clients. Team ownership is the client's ``owner``
field; everything else this project adds (description, additional emails,
listed/is_active) lives in Hydra's free-form ``metadata`` field.
"""

from __future__ import annotations

import dataclasses
import uuid

import requests
from allauth.account.models import EmailAddress
from django.conf import settings

# Every application is constrained to this shape. PKCE strictness (S256-only,
# mandatory) is enforced by Hydra itself via OAUTH2_PKCE_ENFORCED=true (see
# docker-compose.yml), not by this app.
_GRANT_TYPES = ["authorization_code", "refresh_token"]
_RESPONSE_TYPES = ["code"]
_SCOPE = "openid profile email"


class HydraAdminError(Exception):
    """Raised when Hydra's admin API returns an unexpected response.

    Callers reading a challenge (get_login_request/get_consent_request)
    catch this and turn it into a 404 — nothing has been decided yet, so
    failing soft is safe. Callers that decide a challenge's outcome
    (accept_login, accept_consent, reject_consent, accept_logout,
    reject_logout) deliberately do NOT catch this: letting it 500 is the
    right behaviour, since silently swallowing a failed accept/reject could
    misroute a sign-in or leave Hydra's challenge in an ambiguous state.
    """


def _admin_url(path: str) -> str:
    return f"{settings.HYDRA_ADMIN_URL.rstrip('/')}{path}"


def _request(method: str, path: str, **kwargs) -> requests.Response:
    """A single attempt against Hydra's admin API, no retry.

    Every sign-in now has a hard dependency on this API being reachable
    (the old django-oauth-toolkit setup only depended on the local
    database). No retry/backoff here is deliberate for now: HYDRA_ADMIN_URL
    is trusted/internal-only and a transient failure should surface loudly
    (see HydraAdminError) rather than add latency retrying inside a
    user-facing redirect — but this is worth revisiting if Hydra outages
    turn out to be a real source of failed sign-ins in practice.
    """
    response = requests.request(method, _admin_url(path), timeout=10, **kwargs)
    if response.status_code >= 400:
        raise HydraAdminError(
            f"{method} {path} -> {response.status_code}: {response.text}"
        )
    return response


@dataclasses.dataclass
class Application:
    """A Hydra OAuth2 client, decorated with this project's extra fields.

    ``client_secret`` is only ever populated on creation or regeneration —
    Hydra hashes it server-side, so it's never returned on ordinary reads.
    """

    client_id: str
    name: str
    team_id: str
    redirect_uris: list[str] = dataclasses.field(default_factory=list)
    post_logout_redirect_uris: list[str] = dataclasses.field(default_factory=list)
    allowed_cors_origins: list[str] = dataclasses.field(default_factory=list)
    skip_authorization: bool = False
    description: str = ""
    main_app_url: str = ""
    additional_emails: list[str] = dataclasses.field(default_factory=list)
    listed: bool = True
    is_active: bool = True
    client_secret: str | None = None

    @property
    def pk(self):
        return self.client_id

    @property
    def additional_email_list(self):
        return [email.lower() for email in self.additional_emails]

    @classmethod
    def _from_hydra(cls, data: dict) -> "Application":
        metadata = data.get("metadata") or {}
        return cls(
            client_id=data["client_id"],
            name=data.get("client_name", ""),
            team_id=data.get("owner", ""),
            redirect_uris=data.get("redirect_uris") or [],
            post_logout_redirect_uris=data.get("post_logout_redirect_uris") or [],
            allowed_cors_origins=data.get("allowed_cors_origins") or [],
            skip_authorization=bool(data.get("skip_consent")),
            description=metadata.get("description", ""),
            main_app_url=metadata.get("main_app_url", ""),
            additional_emails=metadata.get("additional_emails", []),
            listed=metadata.get("listed", True),
            is_active=metadata.get("is_active", True),
            client_secret=data.get("client_secret"),
        )

    def _metadata(self) -> dict:
        return {
            "description": self.description,
            "main_app_url": self.main_app_url,
            "additional_emails": self.additional_email_list,
            "listed": self.listed,
            "is_active": self.is_active,
        }

    def _client_fields(self) -> dict:
        """Hydra-native fields as a client payload; shared by create/update."""
        return {
            "client_name": self.name,
            "owner": str(self.team_id),
            "grant_types": _GRANT_TYPES,
            "response_types": _RESPONSE_TYPES,
            "scope": _SCOPE,
            "token_endpoint_auth_method": "client_secret_post",
            "redirect_uris": list(self.redirect_uris),
            "post_logout_redirect_uris": list(self.post_logout_redirect_uris),
            "allowed_cors_origins": list(self.allowed_cors_origins),
            "skip_consent": self.skip_authorization,
            "metadata": self._metadata(),
        }


def create_application(
    *, name, team_id, redirect_uris, client_id=None, client_secret=None, **fields
) -> Application:
    """Register a new OAuth2 client in Hydra, owned by ``team_id``.

    ``client_id``/``client_secret`` are normally left to Hydra to generate;
    only seed data (the docker compose demo, tests) pins them.
    """
    draft = Application(
        client_id="",
        name=name,
        team_id=str(team_id),
        redirect_uris=list(redirect_uris),
        **fields,
    )
    payload = draft._client_fields()
    if client_id is not None:
        payload["client_id"] = client_id
    if client_secret is not None:
        payload["client_secret"] = client_secret
    response = _request("POST", "/admin/clients", json=payload)
    return Application._from_hydra(response.json())


def get_application(client_id: str) -> Application | None:
    response = requests.get(_admin_url(f"/admin/clients/{client_id}"), timeout=10)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise HydraAdminError(f"GET client {client_id} -> {response.status_code}")
    return Application._from_hydra(response.json())


def _list_all_applications() -> list[Application]:
    """Every application in Hydra, active or not, regardless of owner.

    Hydra has no owner filter on its list endpoint, so callers fetch
    everything and filter client-side.

    Scaling limitation: fetches a single page of up to 500 clients and does
    not follow Hydra's page_token cursor, so beyond 500 total clients this
    silently truncates rather than erroring. This function is on the hot
    path for every sign-in (is_signin_domain_allowed) and every directory
    page view (ApplicationDirectory), so there's no caching either — fine at
    prototype/demo scale; would need real pagination (or a local read-through
    cache) before this could support more than a few hundred applications.
    """
    response = _request("GET", "/admin/clients", params={"page_size": 500})
    return [Application._from_hydra(c) for c in response.json()]


def list_team_applications(
    team_id, *, include_inactive: bool = False
) -> list[Application]:
    """Every application owned by a team, alphabetical by name."""
    apps = [a for a in _list_all_applications() if a.team_id == str(team_id)]
    if not include_inactive:
        apps = [a for a in apps if a.is_active]
    return sorted(apps, key=lambda a: a.name.lower())


def list_all_active_applications() -> list[Application]:
    """Every active application across every team.

    Used by the global sign-in gate (users.domains) and the applications
    directory (users.views.ApplicationDirectory).
    """
    return [a for a in _list_all_applications() if a.is_active]


def update_application(client_id: str, **kwargs) -> Application:
    existing = get_application(client_id)
    if existing is None:
        raise HydraAdminError(f"No such client {client_id}")
    merged = dataclasses.replace(existing, **kwargs)
    response = _request(
        "PUT", f"/admin/clients/{client_id}", json=merged._client_fields()
    )
    return Application._from_hydra(response.json())


def regenerate_secret(client_id: str) -> Application:
    response = _request(
        "PATCH",
        f"/admin/clients/{client_id}",
        json=[{"op": "replace", "path": "/client_secret", "value": _new_secret()}],
    )
    return Application._from_hydra(response.json())


def _new_secret() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


def soft_delete(client_id: str) -> None:
    """Mark an application inactive without removing it from Hydra.

    Preserves credentials and sign-in history (SignInEvent keeps its own
    denormalised record).
    """
    update_application(client_id, is_active=False)


# ---------------------------------------------------------------------------
# Login, consent and logout challenges: Hydra redirects the browser here with
# a challenge id and this app calls back into its admin API to accept/reject
# it, which returns a redirect_to URL (either back into Hydra, or to the
# relying party).
# ---------------------------------------------------------------------------


def get_login_request(challenge: str) -> dict:
    response = _request(
        "GET",
        "/admin/oauth2/auth/requests/login",
        params={"login_challenge": challenge},
    )
    return response.json()


def application_from_client(client: dict) -> Application:
    """Build an Application from the ``client`` embedded in a login/consent
    request, avoiding a separate GET /admin/clients/{id} call."""
    return Application._from_hydra(client)


def accept_login(challenge: str, *, subject: str, remember: bool = False) -> str:
    response = _request(
        "PUT",
        "/admin/oauth2/auth/requests/login/accept",
        params={"login_challenge": challenge},
        json={"subject": subject, "remember": remember},
    )
    return response.json()["redirect_to"]


def get_consent_request(challenge: str) -> dict:
    response = _request(
        "GET",
        "/admin/oauth2/auth/requests/consent",
        params={"consent_challenge": challenge},
    )
    return response.json()


def accept_consent(challenge: str, *, grant_scope: list[str], user) -> str:
    """Accept a consent request, asserting the user's email in the ID token.

    ``email_verified`` reflects the real EmailAddress state rather than
    hardcoding True, so a future unverified-login path can't mint a
    "verified" identity.
    """
    email_verified = EmailAddress.objects.filter(
        user=user, email__iexact=user.email, verified=True
    ).exists()
    session = {
        "id_token": {
            "email": user.email,
            "email_verified": email_verified,
            "name": user.get_full_name() or user.email,
            "preferred_username": user.email,
        }
    }
    response = _request(
        "PUT",
        "/admin/oauth2/auth/requests/consent/accept",
        params={"consent_challenge": challenge},
        json={
            "grant_scope": grant_scope,
            "grant_access_token_audience": [],
            "session": session,
            # Not remembered: whether consent is shown again is governed by
            # the application's own skip_authorization setting, not Hydra's
            # remember mechanism (see HydraConsentView.get).
            "remember": False,
        },
    )
    return response.json()["redirect_to"]


def reject_consent(challenge: str) -> str:
    response = _request(
        "PUT",
        "/admin/oauth2/auth/requests/consent/reject",
        params={"consent_challenge": challenge},
        json={"error": "access_denied", "error_description": "User denied access"},
    )
    return response.json()["redirect_to"]


def accept_logout(challenge: str) -> str:
    response = _request(
        "PUT",
        "/admin/oauth2/auth/requests/logout/accept",
        params={"logout_challenge": challenge},
    )
    return response.json()["redirect_to"]


def reject_logout(challenge: str) -> str:
    response = _request(
        "PUT",
        "/admin/oauth2/auth/requests/logout/reject",
        params={"logout_challenge": challenge},
    )
    return response.json()["redirect_to"]


def revoke_consent(*, user_id, client_id) -> None:
    """Revoke a user's consent grant for one application.

    Immediately invalidates its already-issued access/refresh tokens
    (confirmed via introspection). Login-session revocation isn't needed:
    this app always accepts with ``remember=False``, so Hydra re-issues a
    fresh login-challenge — re-running the domain check — on every
    authorization request regardless. Scoped to one client so removing one
    team's domain/membership doesn't touch unrelated access. A 404 (no grant
    to revoke) is not an error.
    """
    response = requests.delete(
        _admin_url("/admin/oauth2/auth/sessions/consent"),
        params={"subject": str(user_id), "client": client_id},
        timeout=10,
    )
    if response.status_code not in (204, 404):
        raise HydraAdminError(
            f"DELETE consent sessions for {user_id}/{client_id} "
            f"-> {response.status_code}: {response.text}"
        )


def revoke_team_consent(*, user_id, team_id) -> None:
    """Revoke a user's consent for every application owned by a team.

    Includes soft-deleted applications: a token issued before an app was
    soft-deleted is still live until it expires, so a domain/membership
    removal must still revoke it, even though the app itself now 404s for
    new sign-ins.
    """
    for application in list_team_applications(team_id, include_inactive=True):
        revoke_consent(user_id=user_id, client_id=application.client_id)
