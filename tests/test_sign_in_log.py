import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.models import SignInEvent, Team

from tests.conftest import REDIRECT_URI, authorize_params, pkce_pair

User = get_user_model()
Application = get_application_model()


def _team(name, domains):
    team = Team.objects.create(name=name)
    for domain in domains:
        team.allowed_email_domains.create(domain=domain)
    return team


def _app(name, team, **kwargs):
    return Application.objects.create(
        name=name,
        client_type=Application.CLIENT_CONFIDENTIAL,
        redirect_uris=REDIRECT_URI,
        team=team,
        **kwargs,
    )


def _params(app):
    _, code_challenge = pkce_pair()
    return authorize_params(client_id=app.client_id, code_challenge=code_challenge)


@pytest.fixture
def allowed_user(db):
    return User.objects.create_user(email="user@allowed.com")


def test_consent_authorize_records_event(client, allowed_user):
    app = _app("App", _team("T", ["allowed.com"]))
    client.force_login(allowed_user)

    response = client.post("/o/authorize/", {**_params(app), "allow": "Authorize"})
    assert response.status_code == 302

    event = SignInEvent.objects.get()
    assert event.user == allowed_user
    assert event.application == app


def test_skip_authorization_records_event(client, allowed_user):
    app = _app("App", _team("T", ["allowed.com"]), skip_authorization=True)
    client.force_login(allowed_user)

    response = client.get("/o/authorize/", _params(app))
    assert response.status_code == 302
    assert SignInEvent.objects.filter(user=allowed_user, application=app).count() == 1


def test_blocked_user_records_no_event(client, db):
    user = User.objects.create_user(email="user@blocked.com")
    app = _app("App", _team("T", ["allowed.com"]))
    client.force_login(user)

    response = client.get("/o/authorize/", _params(app))
    assert response.status_code == 403
    assert not SignInEvent.objects.exists()


def test_hidden_application_records_no_event(client, allowed_user):
    app = _app("App", _team("T", ["allowed.com"]), is_active=False)
    client.force_login(allowed_user)

    response = client.get("/o/authorize/", _params(app))
    assert response.status_code == 404
    assert not SignInEvent.objects.exists()
