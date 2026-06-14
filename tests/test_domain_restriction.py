import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.views import _is_domain_allowed

from tests.conftest import authorize_params_for

User = get_user_model()
Application = get_application_model()


@pytest.fixture
def app(make_team, make_application):
    return make_application(
        make_team("Restricted Team", domains=["allowed.com"]), name="Restricted App"
    )


@pytest.fixture
def no_domain_app(make_team, make_application):
    return make_application(make_team("No Domain Team"), name="No Domain App")


# ---------------------------------------------------------------------------
# Unit tests for the helper function
# ---------------------------------------------------------------------------


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
    assert _is_domain_allowed(Application(team=team), email) is expected


@pytest.mark.parametrize(
    "additional_emails,email,expected",
    [
        ("vip@blocked.com", "vip@blocked.com", True),  # listed VIP bypasses domain
        ("vip@blocked.com", "VIP@BLOCKED.COM", True),  # case-insensitive
        ("VIP@BLOCKED.COM", "vip@blocked.com", True),  # stored uppercase still matches
        ("a@blocked.com b@blocked.com", "b@blocked.com", True),  # multiple, space sep
        ("vip@blocked.com", "other@blocked.com", False),  # not listed, domain blocked
        ("", "user@blocked.com", False),  # no additional emails
    ],
)
def test_additional_emails_bypass_domain(make_team, additional_emails, email, expected):
    team = make_team("VIP Team", domains=["allowed.com"])
    application = Application(team=team, additional_emails=additional_emails)
    assert _is_domain_allowed(application, email) is expected


# ---------------------------------------------------------------------------
# Authorization view — GET (consent screen)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("allowed_user", 200),
        ("blocked_user", 403),
    ],
)
def test_authorize_get_domain_check(
    request, client, user_fixture, expected_status, app
):
    client.force_login(request.getfixturevalue(user_fixture))
    response = client.get("/o/authorize/", authorize_params_for(app))
    assert response.status_code == expected_status


def test_authorize_get_no_domain_app_denies_all(
    client, allowed_user, blocked_user, no_domain_app
):
    # A team that lists no domains admits no one (fail closed).
    params = authorize_params_for(no_domain_app)
    for user in (allowed_user, blocked_user):
        client.force_login(user)
        assert client.get("/o/authorize/", params).status_code == 403


def test_authorize_hidden_application_is_404(client, allowed_user, app):
    # A soft-deleted application can never sign anyone in, even an allowed user.
    app.is_active = False
    app.save(update_fields=["is_active"])
    client.force_login(allowed_user)
    response = client.get("/o/authorize/", authorize_params_for(app))
    assert response.status_code == 404


def test_authorize_get_unauthenticated_redirects(client, app):
    response = client.get("/o/authorize/", authorize_params_for(app))
    assert response.status_code == 302  # redirect to login, no 403


# ---------------------------------------------------------------------------
# Authorization view — POST (form submission)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("allowed_user", 302),  # success → redirect with auth code
        ("blocked_user", 403),
    ],
)
def test_authorize_post_domain_check(
    request, client, user_fixture, expected_status, app
):
    user = request.getfixturevalue(user_fixture)
    client.force_login(user)
    params = authorize_params_for(app)
    response = client.post("/o/authorize/", {**params, "allow": "Authorize"})
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# Multi-domain and case-insensitivity via the view
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email,allowed_domains,expected_status",
    [
        ("user@alpha.com", ["alpha.com", "beta.com"], 200),
        ("user@beta.com", ["alpha.com", "beta.com"], 200),
        ("user@gamma.com", ["alpha.com", "beta.com"], 403),
        ("user@ALPHA.COM", ["alpha.com"], 200),  # email domain uppercase
        ("user@alpha.com", ["ALPHA.COM"], 200),  # whitelist uppercase
    ],
)
def test_authorize_domain_cases(
    client, make_team, make_application, email, allowed_domains, expected_status
):
    user = User.objects.create_user(email=email)
    application = make_application(make_team("Case Team", domains=allowed_domains))
    client.force_login(user)
    response = client.get("/o/authorize/", authorize_params_for(application))
    assert response.status_code == expected_status


def test_authorize_403_shows_app_name(client, blocked_user, app):
    client.force_login(blocked_user)
    response = client.get("/o/authorize/", authorize_params_for(app))
    assert response.status_code == 403
    assert app.name in response.content.decode()


def test_authorize_unknown_client_id(client, allowed_user):
    client.force_login(allowed_user)
    params = {
        "client_id": "nonexistent-client-id",
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": "http://localhost/callback",
        "code_challenge": "x" * 43,
        "code_challenge_method": "S256",
    }
    response = client.get("/o/authorize/", params)
    assert response.status_code != 500
