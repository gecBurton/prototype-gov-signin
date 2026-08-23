"""Hydra admin-API failure handling, verified through the actual views.

get_login_request/get_consent_request (reads, nothing decided yet) are
caught by their views and turned into a 404. accept_login/accept_consent/
reject_consent/accept_logout/reject_logout (writes that decide a challenge's
outcome) are deliberately NOT caught anywhere — see the HydraAdminError
docstring in users/hydra.py for why letting these 500 is the intended
behaviour, not an oversight.
"""

import pytest

from users import hydra


def _raise_hydra_error(*args, **kwargs):
    raise hydra.HydraAdminError("simulated Hydra outage")


def test_login_request_read_failure_is_404(
    client, fake_hydra, allowed_user, monkeypatch
):
    monkeypatch.setattr(hydra, "get_login_request", _raise_hydra_error)
    client.force_login(allowed_user)

    response = client.get("/o/login/?login_challenge=whatever")

    assert response.status_code == 404


def test_consent_request_read_failure_is_404(
    client, fake_hydra, allowed_user, monkeypatch
):
    monkeypatch.setattr(hydra, "get_consent_request", _raise_hydra_error)
    client.force_login(allowed_user)

    response = client.get("/o/consent/?consent_challenge=whatever")

    assert response.status_code == 404


def test_login_accept_failure_is_not_swallowed(
    client, fake_hydra, allowed_user, make_team, make_application, monkeypatch
):
    """A Hydra outage while accepting a login raises, rather than being
    silently turned into a redirect or misrouted sign-in."""
    app = make_application(make_team("T", domains=["allowed.com"]))
    monkeypatch.setattr(hydra, "accept_login", _raise_hydra_error)
    challenge = fake_hydra.start_login(app.client_id)
    client.force_login(allowed_user)

    with pytest.raises(hydra.HydraAdminError):
        client.get(f"/o/login/?login_challenge={challenge}")


def test_consent_accept_failure_is_not_swallowed(
    client, fake_hydra, allowed_user, make_team, make_application, monkeypatch
):
    app = make_application(make_team("T", domains=["allowed.com"]))
    monkeypatch.setattr(hydra, "accept_consent", _raise_hydra_error)
    challenge = fake_hydra.start_consent(app.client_id)
    client.force_login(allowed_user)

    with pytest.raises(hydra.HydraAdminError):
        client.post(
            "/o/consent/", {"consent_challenge": challenge, "allow": "Authorize"}
        )


def test_consent_reject_failure_is_not_swallowed(
    client, fake_hydra, allowed_user, monkeypatch
):
    monkeypatch.setattr(hydra, "reject_consent", _raise_hydra_error)
    client.force_login(allowed_user)

    with pytest.raises(hydra.HydraAdminError):
        client.post("/o/consent/", {"consent_challenge": "whatever"})


def test_logout_accept_failure_is_not_swallowed(client, fake_hydra, monkeypatch):
    monkeypatch.setattr(hydra, "accept_logout", _raise_hydra_error)

    with pytest.raises(hydra.HydraAdminError):
        client.post("/o/logout/", {"logout_challenge": "whatever", "allow": "Sign out"})


def test_logout_reject_failure_is_not_swallowed(client, fake_hydra, monkeypatch):
    monkeypatch.setattr(hydra, "reject_logout", _raise_hydra_error)

    with pytest.raises(hydra.HydraAdminError):
        client.post("/o/logout/", {"logout_challenge": "whatever"})
