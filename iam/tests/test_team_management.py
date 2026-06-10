import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# TeamManage GET
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("owner", 200),
        ("stranger", 200),  # teamless users see the page, not forbidden
        (None, 302),  # unauthenticated → login redirect
    ],
)
def test_team_page_access(request, client, user_fixture, expected_status, db):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.get("/o/team/")
    assert response.status_code == expected_status


def test_team_page_shows_members(client, owner, team):
    client.force_login(owner)
    response = client.get("/o/team/")
    assert owner.email in response.content.decode()


def test_team_page_teamless_shows_explanation(client, stranger):
    client.force_login(stranger)
    response = client.get("/o/team/")
    assert "not a member of any team" in response.content.decode()


# ---------------------------------------------------------------------------
# TeamManage POST — adding members
# ---------------------------------------------------------------------------


def test_add_member_success(client, owner, stranger):
    client.force_login(owner)
    response = client.post("/o/team/", {"email": stranger.email})
    assert response.status_code == 302
    stranger.refresh_from_db()
    assert stranger.team_id == owner.team_id


@pytest.mark.parametrize(
    "email,error_fragment",
    [
        ("nobody@example.com", "No user found with email nobody@example.com"),
        ("owner@example.com", "owner@example.com is already a team member"),
    ],
)
def test_add_member_validation(client, owner, email, error_fragment):
    client.force_login(owner)
    response = client.post("/o/team/", {"email": email})
    assert response.status_code == 200
    assert error_fragment in response.content.decode()


def test_add_member_teamless_user_forbidden(client, stranger):
    client.force_login(stranger)
    response = client.post("/o/team/", {"email": "anyone@example.com"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# TeamMemberRemove POST
# ---------------------------------------------------------------------------


def test_remove_member_success(client, owner, stranger, team):
    stranger.team = team
    stranger.save()
    client.force_login(owner)
    response = client.post(f"/o/team/{stranger.pk}/remove/")
    assert response.status_code == 302
    stranger.refresh_from_db()
    assert stranger.team is None


def test_remove_non_member_is_noop(client, owner, stranger):
    client.force_login(owner)
    response = client.post(f"/o/team/{stranger.pk}/remove/")
    assert response.status_code == 302
    stranger.refresh_from_db()
    assert stranger.team is None


def test_remove_member_invalid_user_pk(client, owner):
    client.force_login(owner)
    response = client.post("/o/team/99999/remove/")
    assert response.status_code == 404


def test_remove_member_teamless_user_forbidden(client, stranger):
    other = User.objects.create_user(username="other", email="other@example.com")
    client.force_login(stranger)
    response = client.post(f"/o/team/{other.pk}/remove/")
    assert response.status_code == 403
