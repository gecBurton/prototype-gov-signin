import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model

User = get_user_model()
Application = get_application_model()


@pytest.fixture
def co_owner(team):
    user = User.objects.create_user(username="co_owner", email="co-owner@example.com")
    user.team = team
    user.save()
    return user


# ---------------------------------------------------------------------------
# Access control — GET and POST to per-app owner endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 404), (None, 302)],
    indirect=["authed_client"],
)
def test_owners_page_access(authed_client, expected_status, app):
    assert authed_client.get(f"/o/applications/{app.pk}/owners/").status_code == expected_status


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("stranger", 404), (None, 302)],
    indirect=["authed_client"],
)
@pytest.mark.parametrize("suffix", [
    pytest.param("owners/", id="add"),
    pytest.param("owners/99999/remove/", id="remove"),
])
def test_owner_endpoint_blocked_for_non_member(authed_client, expected_status, suffix, app):
    assert authed_client.post(f"/o/applications/{app.pk}/{suffix}").status_code == expected_status


# ---------------------------------------------------------------------------
# Adding team members
# ---------------------------------------------------------------------------


def test_add_member_success(client, owner, stranger, app):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/", {"email": stranger.email})
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
    assert client.post(f"/o/applications/{app.pk}/owners/{co_owner.pk}/remove/").status_code == 302
    co_owner.refresh_from_db()
    assert co_owner.team is None


def test_remove_member_invalid_user_pk(client, owner, app):
    client.force_login(owner)
    assert client.post(f"/o/applications/{app.pk}/owners/99999/remove/").status_code == 404


def test_remove_non_member_is_noop(client, owner, stranger, app):
    client.force_login(owner)
    client.post(f"/o/applications/{app.pk}/owners/{stranger.pk}/remove/")
    stranger.refresh_from_db()
    assert stranger.team is None
