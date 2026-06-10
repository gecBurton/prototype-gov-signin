import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# TeamManage GET
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 200), (None, 302)],
    indirect=["authed_client"],
)
def test_team_page_access(authed_client, expected_status):
    assert authed_client.get("/o/team/").status_code == expected_status


def test_team_page_shows_members(client, owner):
    client.force_login(owner)
    assert owner.email in client.get("/o/team/").content.decode()


def test_team_page_teamless_shows_explanation(client, stranger):
    client.force_login(stranger)
    assert "not a member of any team" in client.get("/o/team/").content.decode()


# ---------------------------------------------------------------------------
# POST endpoints — forbidden for teamless users
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["/o/team/", "/o/team/00000000-0000-0000-0000-000000000000/remove/"]
)
def test_post_forbidden_for_teamless_user(client, stranger, url):
    client.force_login(stranger)
    assert client.post(url).status_code == 403


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


# ---------------------------------------------------------------------------
# TeamMemberRemove POST
# ---------------------------------------------------------------------------


def test_remove_member_success(client, owner, stranger, team):
    stranger.team = team
    stranger.save()
    client.force_login(owner)
    assert client.post(f"/o/team/{stranger.pk}/remove/").status_code == 302
    stranger.refresh_from_db()
    assert stranger.team is None


def test_remove_non_member_is_noop(client, owner, stranger):
    client.force_login(owner)
    client.post(f"/o/team/{stranger.pk}/remove/")
    stranger.refresh_from_db()
    assert stranger.team is None


def test_remove_member_invalid_user_pk(client, owner):
    client.force_login(owner)
    assert (
        client.post("/o/team/00000000-0000-0000-0000-000000000000/remove/").status_code
        == 404
    )
