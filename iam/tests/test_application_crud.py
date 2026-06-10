import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.models import Team

User = get_user_model()
Application = get_application_model()

_FORM_BASE = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "hash_client_secret": False,
    "client_type": Application.CLIENT_CONFIDENTIAL,
    "authorization_grant_type": Application.GRANT_AUTHORIZATION_CODE,
    "redirect_uris": "http://localhost/callback",
    "algorithm": "RS256",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def team(db):
    return Team.objects.create(name="Test Team")


@pytest.fixture
def owner(team):
    user = User.objects.create_user(username="owner", email="owner@example.com")
    user.team = team
    user.save()
    return user


@pytest.fixture
def stranger(db):
    return User.objects.create_user(username="stranger", email="stranger@example.com")


@pytest.fixture
def app(owner, team):
    return Application.objects.create(
        name="Test App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="http://localhost/callback",
        team=team,
    )


# ---------------------------------------------------------------------------
# Start page
# ---------------------------------------------------------------------------


def test_start_page(client):
    response = client.get("/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# ApplicationList
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("owner", 200),
        ("stranger", 200),  # empty list, not forbidden
        (None, 302),  # unauthenticated → login redirect
    ],
)
def test_list_access(request, client, user_fixture, expected_status, app):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.get("/o/applications/")
    assert response.status_code == expected_status


def test_list_shows_only_owned_apps(client, owner, stranger, app):
    client.force_login(owner)
    assert app.name in client.get("/o/applications/").content.decode()

    client.force_login(stranger)
    assert app.name not in client.get("/o/applications/").content.decode()


# ---------------------------------------------------------------------------
# ApplicationDetail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("owner", 200),
        ("stranger", 404),
        (None, 302),
    ],
)
def test_detail_access(request, client, user_fixture, expected_status, app):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.get(f"/o/applications/{app.pk}/")
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# ApplicationUpdate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("owner", 200),
        ("stranger", 404),
        (None, 302),
    ],
)
def test_update_access(request, client, user_fixture, expected_status, app):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.get(f"/o/applications/{app.pk}/update/")
    assert response.status_code == expected_status


def test_update_saves_changes(client, owner, app):
    client.force_login(owner)
    response = client.post(
        f"/o/applications/{app.pk}/update/",
        {**_FORM_BASE, "name": "Renamed App", "client_id": app.client_id},
    )
    assert response.status_code == 302
    app.refresh_from_db()
    assert app.name == "Renamed App"


# ---------------------------------------------------------------------------
# ApplicationDelete
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("owner", 200),
        ("stranger", 404),
        (None, 302),
    ],
)
def test_delete_access(request, client, user_fixture, expected_status, app):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.get(f"/o/applications/{app.pk}/delete/")
    assert response.status_code == expected_status


def test_delete_removes_application(client, owner, app):
    client.force_login(owner)
    pk = app.pk
    response = client.post(f"/o/applications/{app.pk}/delete/")
    assert response.status_code == 302
    assert not Application.objects.filter(pk=pk).exists()


# ---------------------------------------------------------------------------
# ApplicationRegistration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("owner", 200),
        (None, 302),
    ],
)
def test_registration_page_access(request, client, user_fixture, expected_status, db):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.get("/o/applications/register/")
    assert response.status_code == expected_status


def test_registration_assigns_creators_team(client, owner):
    client.force_login(owner)
    response = client.post(
        "/o/applications/register/",
        {**_FORM_BASE, "name": "New App"},
    )
    assert response.status_code == 302
    app = Application.objects.get(name="New App")
    assert app.team_id == owner.team_id


# ---------------------------------------------------------------------------
# POST write actions blocked for non-owners
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("stranger", 404),
        (None, 302),
    ],
)
def test_update_post_blocked_for_non_owner(
    request, client, user_fixture, expected_status, app
):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.post(
        f"/o/applications/{app.pk}/update/",
        {**_FORM_BASE, "name": "Hacked", "client_id": app.client_id},
    )
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("stranger", 404),
        (None, 302),
    ],
)
def test_delete_post_blocked_for_non_owner(
    request, client, user_fixture, expected_status, app
):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.post(f"/o/applications/{app.pk}/delete/")
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# Redirect destinations
# ---------------------------------------------------------------------------


def test_delete_redirects_to_list(client, owner, app):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/delete/")
    assert response["Location"] == "/o/applications/"


def test_registration_redirects_to_detail(client, owner):
    client.force_login(owner)
    response = client.post(
        "/o/applications/register/", {**_FORM_BASE, "name": "New App"}
    )
    app = Application.objects.get(name="New App")
    assert response["Location"] == f"/o/applications/{app.pk}/"


# ---------------------------------------------------------------------------
# Remove non-owner is a silent no-op
# ---------------------------------------------------------------------------


def test_remove_non_member_is_noop(client, owner, stranger, app):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/{stranger.pk}/remove/")
    assert response.status_code == 302
    stranger.refresh_from_db()
    assert stranger.team is None
