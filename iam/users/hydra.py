"""Thin client for Ory Hydra's admin API, plus the Application wrapper.

Applications are Hydra OAuth2 clients, not a Django model. Team ownership
is the client's ``owner`` field; extra fields (description, additional
emails, listed/is_active) live in Hydra's ``metadata`` field.
"""

from __future__ import annotations

import dataclasses
import uuid

import requests
from allauth.account.models import EmailAddress
from django.conf import settings

# PKCE strictness (S256-only, mandatory) is enforced by Hydra itself via
# OAUTH2_PKCE_ENFORCED=true (docker-compose.yml), not by this app.
_GRANT_TYPES = ["authorization_code", "refresh_token"]
_RESPONSE_TYPES = ["code"]
_SCOPE = "openid profile email"


class HydraAdminError(Exception):
    """Raised when Hydra's admin API returns an unexpected response.

    get_login_request/get_consent_request catch this and 404 (nothing
    decided yet). accept/reject calls deliberately don't catch it — a
    failure there should 500, not silently misroute a sign-in.
    """


def _admin_url(path: str) -> str:
    return f"{settings.HYDRA_ADMIN_URL.rstrip('/')}{path}"


def _request(method: str, path: str, **kwargs) -> requests.Response:
    # No retry: HYDRA_ADMIN_URL is trusted/internal-only, and a transient
    # failure should surface loudly rather than add latency retrying inside
    # a user-facing redirect.
    response = requests.request(method, _admin_url(path), timeout=10, **kwargs)
    if response.status_code >= 400:
        raise HydraAdminError(
            f"{method} {path} -> {response.status_code}: {response.text}"
        )
    return response


@dataclasses.dataclass
class Application:
    """A Hydra OAuth2 client, decorated with this project's extra fields.

    client_secret is only populated on creation/regeneration; Hydra hashes
    it server-side and never returns it on ordinary reads.
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

    client_id/client_secret are normally left to Hydra to generate; only
    seed data (the docker compose demo, tests) pins them.
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

    Hydra has no owner filter, so callers fetch everything and filter
    client-side. Fetches one page of up to 500 and does not follow Hydra's
    page_token cursor, so beyond 500 clients this silently truncates. Hot
    path for every sign-in and every directory page view — fine at
    prototype scale, needs real pagination or caching beyond that.
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
    """Mark an application inactive without removing it from Hydra."""
    update_application(client_id, is_active=False)


# ---------------------------------------------------------------------------
# Login, consent and logout challenges: Hydra redirects the browser here with
# a challenge id; this app calls back into its admin API to accept/reject it,
# which returns a redirect_to URL (back into Hydra, or to the relying party).
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

    email_verified reflects the real EmailAddress state, not a hardcoded True.
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
            # Not remembered: consent-skipping is governed by the
            # application's own skip_authorization, not Hydra's remember.
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
    """Revoke a user's consent grant for one application, invalidating its
    already-issued tokens. Scoped to one client so removing one team's
    domain/membership doesn't touch unrelated access. A 404 is not an error.
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
    """Revoke a user's consent for every application owned by a team,
    including soft-deleted ones (a token issued before soft-delete is
    still live)."""
    for application in list_team_applications(team_id, include_inactive=True):
        revoke_consent(user_id=user_id, client_id=application.client_id)
