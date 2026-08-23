import pytest

from tests.conftest import login_code, make_hydra_application


@pytest.mark.django_db
def test_full_login_and_consent_flow(
    client, fake_hydra, demo_team, demo_user, mailoutbox
):
    """The parts of the OIDC flow this app is responsible for.

    Ory Hydra owns the actual authorization/token/userinfo endpoints and is
    not running in the unit test suite (see tests/conftest.py's fake_hydra),
    so this test covers exactly what this app does: deciding, given a Hydra
    login_challenge and then a consent_challenge, whether the user may sign
    in to a given application, and recording the SignInEvent. The full
    end-to-end flow (through Hydra's real /oauth2/token endpoint) is covered
    by integration_tests/ against the real docker compose stack.
    """
    application = make_hydra_application(fake_hydra, demo_team, name="Grafana")
    login_challenge = fake_hydra.start_login(application.client_id)

    # 1. Unauthenticated user hits the login view — bounced to allauth's login,
    # preserving ?next= so they land back here once authenticated.
    response = client.get(f"/o/login/?login_challenge={login_challenge}")
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

    # 4. Authenticated + allowed user's login request is accepted, redirecting
    # back into Hydra to continue the flow.
    response = client.get(f"/o/login/?login_challenge={login_challenge}")
    assert response.status_code == 302
    assert "flow=login" in response["Location"]

    # 5. Hydra would now redirect to the consent endpoint with its own
    # challenge; simulate that.
    consent_challenge = fake_hydra.start_consent(application.client_id)
    response = client.get(f"/o/consent/?consent_challenge={consent_challenge}")
    assert response.status_code == 200  # consent screen shown (not skip_consent)

    response = client.post(
        "/o/consent/",
        {"consent_challenge": consent_challenge, "allow": "Authorize"},
    )
    assert response.status_code == 302
    assert "flow=consent" in response["Location"]

    from users.models import SignInEvent

    event = SignInEvent.objects.get()
    assert event.user == demo_user
    assert event.application_client_id == application.client_id


@pytest.fixture
def demo_team(db):
    from users.models import Team

    team = Team.objects.create(name="Demo")
    team.allowed_email_domains.create(domain="example.com")
    return team


@pytest.fixture
def demo_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(email="demo@example.com")
    user.set_unusable_password()
    user.save()
    return user
