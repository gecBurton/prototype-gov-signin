import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.models import Team

User = get_user_model()
Application = get_application_model()


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
def co_owner(team):
    user = User.objects.create_user(username="co_owner", email="co-owner@example.com")
    user.team = team
    user.save()
    return user


@pytest.fixture
def stranger(db):
    return User.objects.create_user(username="stranger", email="stranger@example.com")


@pytest.fixture
def app(team):
    return Application.objects.create(
        name="Test App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        team=team,
    )


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("owner", 200),
        ("stranger", 404),
        (None, 302),  # unauthenticated → redirect to login
    ],
)
def test_owners_page_access(request, client, user_fixture, expected_status, app):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.get(f"/o/applications/{app.pk}/owners/")
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("stranger", 404),
        (None, 302),
    ],
)
def test_add_member_requires_team_membership(
    request, client, user_fixture, expected_status, app, stranger
):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.post(
        f"/o/applications/{app.pk}/owners/",
        {"email": stranger.email},
    )
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("stranger", 404),
        (None, 302),
    ],
)
def test_remove_member_requires_team_membership(
    request, client, user_fixture, expected_status, app, co_owner
):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.post(f"/o/applications/{app.pk}/owners/{co_owner.pk}/remove/")
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# Adding team members
# ---------------------------------------------------------------------------


def test_add_member_success(client, owner, stranger, app):
    client.force_login(owner)
    response = client.post(
        f"/o/applications/{app.pk}/owners/",
        {"email": stranger.email},
    )
    assert response.status_code == 302
    stranger.refresh_from_db()
    assert stranger.team_id == app.team_id


@pytest.mark.parametrize(
    "email,error_fragment",
    [
        ("nobody@example.com", "No user found with email nobody@example.com"),
        ("owner@example.com", "owner@example.com is already a team member"),
    ],
)
def test_add_member_validation(client, owner, app, email, error_fragment):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/", {"email": email})
    assert response.status_code == 200
    assert error_fragment in response.content.decode()


# ---------------------------------------------------------------------------
# Removing team members
# ---------------------------------------------------------------------------


def test_remove_member_success(client, owner, co_owner, app):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/{co_owner.pk}/remove/")
    assert response.status_code == 302
    co_owner.refresh_from_db()
    assert co_owner.team is None


def test_remove_member_invalid_user_pk(client, owner, app):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/99999/remove/")
    assert response.status_code == 404


def test_remove_non_member_is_noop(client, owner, stranger, app):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/{stranger.pk}/remove/")
    assert response.status_code == 302
    stranger.refresh_from_db()
    assert stranger.team is None
