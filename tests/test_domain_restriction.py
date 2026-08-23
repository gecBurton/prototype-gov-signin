import pytest
from django.contrib.auth import get_user_model
from users.hydra import Application
from users.views import _is_domain_allowed

User = get_user_model()


@pytest.fixture
def app(fake_hydra, make_team, make_application):
    return make_application(
        make_team("Restricted Team", domains=["allowed.com"]), name="Restricted App"
    )


@pytest.fixture
def no_domain_app(fake_hydra, make_team, make_application):
    return make_application(make_team("No Domain Team"), name="No Domain App")


# ---------------------------------------------------------------------------
# Unit tests for the helper function
# ---------------------------------------------------------------------------


def _fake_app(team_id, additional_emails=()):
    return Application(
        client_id="x",
        name="x",
        team_id=str(team_id),
        redirect_uris=[],
        post_logout_redirect_uris=[],
        allowed_cors_origins=[],
        skip_authorization=False,
        additional_emails=list(additional_emails),
    )


@pytest.mark.parametrize(
    "domains,email,expected",
    [
        ([], "anyone@anything.com", False),  # no domains = deny all (fail closed)
        (["allowed.com"], "user@allowed.com", True),
        (["allowed.com"], "user@blocked.com", False),
        (["ALLOWED.COM"], "user@allowed.com", True),  # domains stored lowercase
        (["allowed.com"], "user@ALLOWED.COM", True),  # case-insensitive email
        (["a.com", "b.com", "c.com"], "user@b.com", True),  # multiple domains
        (["a.com", "b.com", "c.com"], "user@d.com", False),
        (["  allowed.com  "], "user@allowed.com", True),  # whitespace tolerance
        (["gov.uk"], "some.one@department.gov.uk", True),  # subdomains match
        (["gov.uk"], "some.one@deep.nested.gov.uk", True),
        (["gov.uk"], "some.one@evilgov.uk", False),  # suffix must be a full label
        (["department.gov.uk"], "some.one@gov.uk", False),  # parent domain no match
    ],
)
def test_is_domain_allowed(make_team, domains, email, expected):
    team = make_team("Test Team", domains=domains)
    assert _is_domain_allowed(_fake_app(team.pk), email) is expected


@pytest.mark.parametrize(
    "additional_emails,email,expected",
    [
        (["vip@blocked.com"], "vip@blocked.com", True),  # listed VIP bypasses domain
        (["vip@blocked.com"], "VIP@BLOCKED.COM", True),  # case-insensitive
        (
            ["VIP@BLOCKED.COM"],
            "vip@blocked.com",
            True,
        ),  # stored uppercase still matches
        (["a@blocked.com", "b@blocked.com"], "b@blocked.com", True),  # multiple
        (["vip@blocked.com"], "other@blocked.com", False),  # not listed, domain blocked
        ([], "user@blocked.com", False),  # no additional emails
    ],
)
def test_additional_emails_bypass_domain(make_team, additional_emails, email, expected):
    team = make_team("VIP Team", domains=["allowed.com"])
    application = _fake_app(team.pk, additional_emails=additional_emails)
    assert _is_domain_allowed(application, email) is expected


# ---------------------------------------------------------------------------
# HydraLoginView — domain check at the login-challenge step
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("allowed_user", 302),  # accepted, redirected back into Hydra
        ("blocked_user", 403),
    ],
)
def test_login_view_domain_check(
    request, client, fake_hydra, user_fixture, expected_status, app
):
    client.force_login(request.getfixturevalue(user_fixture))
    challenge = fake_hydra.start_login(app.client_id)
    response = client.get(f"/o/login/?login_challenge={challenge}")
    assert response.status_code == expected_status


def test_login_view_no_domain_app_denies_all(
    client, fake_hydra, allowed_user, blocked_user, no_domain_app
):
    # A team that lists no domains admits no one (fail closed).
    challenge = fake_hydra.start_login(no_domain_app.client_id)
    for user in (allowed_user, blocked_user):
        client.force_login(user)
        challenge = fake_hydra.start_login(no_domain_app.client_id)
        assert client.get(f"/o/login/?login_challenge={challenge}").status_code == 403


def test_login_view_hidden_application_is_404(client, fake_hydra, allowed_user, app):
    # A soft-deleted application can never sign anyone in, even an allowed user.
    from users import hydra

    hydra.soft_delete(app.client_id)
    client.force_login(allowed_user)
    challenge = fake_hydra.start_login(app.client_id)
    response = client.get(f"/o/login/?login_challenge={challenge}")
    assert response.status_code == 404


def test_login_view_unauthenticated_redirects(client, fake_hydra, app):
    challenge = fake_hydra.start_login(app.client_id)
    response = client.get(f"/o/login/?login_challenge={challenge}")
    assert response.status_code == 302  # redirect to login, no 403


# ---------------------------------------------------------------------------
# Multi-domain and case-insensitivity via the view
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email,allowed_domains,expected_status",
    [
        ("user@alpha.com", ["alpha.com", "beta.com"], 302),
        ("user@beta.com", ["alpha.com", "beta.com"], 302),
        ("user@gamma.com", ["alpha.com", "beta.com"], 403),
        ("user@ALPHA.COM", ["alpha.com"], 302),  # email domain uppercase
        ("user@alpha.com", ["ALPHA.COM"], 302),  # whitelist uppercase
    ],
)
def test_login_view_domain_cases(
    client,
    fake_hydra,
    make_team,
    make_application,
    email,
    allowed_domains,
    expected_status,
):
    user = User.objects.create_user(email=email)
    application = make_application(make_team("Case Team", domains=allowed_domains))
    client.force_login(user)
    challenge = fake_hydra.start_login(application.client_id)
    response = client.get(f"/o/login/?login_challenge={challenge}")
    assert response.status_code == expected_status


def test_login_view_403_shows_app_name(client, fake_hydra, blocked_user, app):
    client.force_login(blocked_user)
    challenge = fake_hydra.start_login(app.client_id)
    response = client.get(f"/o/login/?login_challenge={challenge}")
    assert response.status_code == 403
    assert app.name in response.content.decode()


def test_login_view_unknown_challenge_404s(client, allowed_user):
    client.force_login(allowed_user)
    response = client.get("/o/login/?login_challenge=nonexistent")
    assert response.status_code == 404
