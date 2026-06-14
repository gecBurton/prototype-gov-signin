from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.models import SignInEvent

from tests.conftest import authorize_params_for

User = get_user_model()
Application = get_application_model()


def test_consent_authorize_records_event(
    client, allowed_user, make_team, make_application
):
    app = make_application(make_team("T", domains=["allowed.com"]))
    client.force_login(allowed_user)

    response = client.post(
        "/o/authorize/", {**authorize_params_for(app), "allow": "Authorize"}
    )
    assert response.status_code == 302

    event = SignInEvent.objects.get()
    assert event.user == allowed_user
    assert event.application == app


def test_skip_authorization_records_event(
    client, allowed_user, make_team, make_application
):
    app = make_application(
        make_team("T", domains=["allowed.com"]), skip_authorization=True
    )
    client.force_login(allowed_user)

    response = client.get("/o/authorize/", authorize_params_for(app))
    assert response.status_code == 302
    assert SignInEvent.objects.filter(user=allowed_user, application=app).count() == 1


def test_blocked_user_records_no_event(
    client, blocked_user, make_team, make_application
):
    app = make_application(make_team("T", domains=["allowed.com"]))
    client.force_login(blocked_user)

    response = client.get("/o/authorize/", authorize_params_for(app))
    assert response.status_code == 403
    assert not SignInEvent.objects.exists()


def test_hidden_application_records_no_event(
    client, allowed_user, make_team, make_application
):
    app = make_application(make_team("T", domains=["allowed.com"]), is_active=False)
    client.force_login(allowed_user)

    response = client.get("/o/authorize/", authorize_params_for(app))
    assert response.status_code == 404
    assert not SignInEvent.objects.exists()
