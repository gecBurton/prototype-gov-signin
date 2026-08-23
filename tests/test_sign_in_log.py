from users.models import SignInEvent


def test_consent_authorize_records_event(
    client, fake_hydra, allowed_user, make_team, make_application
):
    app = make_application(make_team("T", domains=["allowed.com"]))
    client.force_login(allowed_user)

    login_challenge = fake_hydra.start_login(app.client_id)
    assert client.get(f"/o/login/?login_challenge={login_challenge}").status_code == 302

    consent_challenge = fake_hydra.start_consent(app.client_id)
    response = client.post(
        "/o/consent/", {"consent_challenge": consent_challenge, "allow": "Authorize"}
    )
    assert response.status_code == 302

    event = SignInEvent.objects.get()
    assert event.user == allowed_user
    assert event.application_client_id == app.client_id


def test_skip_authorization_records_event(
    client, fake_hydra, allowed_user, make_team, make_application
):
    app = make_application(
        make_team("T", domains=["allowed.com"]), skip_authorization=True
    )
    client.force_login(allowed_user)

    consent_challenge = fake_hydra.start_consent(app.client_id)
    fake_hydra.consent_requests[consent_challenge]["skip"] = True
    response = client.get(f"/o/consent/?consent_challenge={consent_challenge}")
    assert response.status_code == 302
    assert (
        SignInEvent.objects.filter(
            user=allowed_user, application_client_id=app.client_id
        ).count()
        == 1
    )


def test_blocked_user_records_no_event(
    client, fake_hydra, blocked_user, make_team, make_application
):
    app = make_application(make_team("T", domains=["allowed.com"]))
    client.force_login(blocked_user)

    login_challenge = fake_hydra.start_login(app.client_id)
    response = client.get(f"/o/login/?login_challenge={login_challenge}")
    assert response.status_code == 403
    assert not SignInEvent.objects.exists()


def test_hidden_application_records_no_event(
    client, fake_hydra, allowed_user, make_team, make_application
):
    from users import hydra

    app = make_application(make_team("T", domains=["allowed.com"]))
    hydra.soft_delete(app.client_id)
    client.force_login(allowed_user)

    login_challenge = fake_hydra.start_login(app.client_id)
    response = client.get(f"/o/login/?login_challenge={login_challenge}")
    assert response.status_code == 404
    assert not SignInEvent.objects.exists()
