import pytest
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from users.models import Team

User = get_user_model()


@pytest.fixture
def second_team(owner):
    team = Team.objects.create(name="Second Team")
    owner.teams.add(team)
    return team


# ---------------------------------------------------------------------------
# TeamList GET
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 200), (None, 302)],
    indirect=["authed_client"],
)
def test_team_list_access(authed_client, expected_status):
    assert authed_client.get("/o/teams/").status_code == expected_status


def test_team_list_shows_all_teams(client, owner, team, second_team):
    client.force_login(owner)
    content = client.get("/o/teams/").content.decode()
    assert team.name in content
    assert second_team.name in content


def test_team_list_teamless_shows_explanation(client, stranger):
    client.force_login(stranger)
    assert "not a member of any team" in client.get("/o/teams/").content.decode()


# ---------------------------------------------------------------------------
# Team deletion
# ---------------------------------------------------------------------------


def test_delete_team_with_applications_is_blocked(team, app):
    with pytest.raises(ProtectedError):
        team.delete()


def test_delete_team_without_applications_succeeds(team):
    team.delete()
    assert not Team.objects.filter(pk=team.pk).exists()


# ---------------------------------------------------------------------------
# TeamDetail GET
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 404), (None, 302)],
    indirect=["authed_client"],
)
def test_team_detail_access(authed_client, expected_status, team):
    assert authed_client.get(f"/o/teams/{team.pk}/").status_code == expected_status


def test_team_detail_shows_members(client, owner, team):
    client.force_login(owner)
    assert owner.email in client.get(f"/o/teams/{team.pk}/").content.decode()


def test_team_detail_shows_applications(client, owner, team, app):
    client.force_login(owner)
    assert app.name in client.get(f"/o/teams/{team.pk}/").content.decode()


# ---------------------------------------------------------------------------
# POST endpoints — 404 for non-members of the team
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("", id="add-member"),
        pytest.param(
            "members/00000000-0000-0000-0000-000000000000/remove/", id="remove-member"
        ),
        pytest.param("domains/", id="add-domain"),
        pytest.param(
            "domains/00000000-0000-0000-0000-000000000000/remove/", id="remove-domain"
        ),
    ],
)
def test_post_not_found_for_non_member(client, stranger, team, suffix):
    client.force_login(stranger)
    assert client.post(f"/o/teams/{team.pk}/{suffix}").status_code == 404


# ---------------------------------------------------------------------------
# TeamDetail POST — adding members
# ---------------------------------------------------------------------------


def test_add_member_success(client, owner, stranger, team):
    client.force_login(owner)
    response = client.post(f"/o/teams/{team.pk}/", {"email": stranger.email})
    assert response.status_code == 302
    assert stranger.teams.filter(pk=team.pk).exists()


def test_add_member_keeps_existing_memberships(client, owner, stranger, team):
    other = Team.objects.create(name="Other Team")
    stranger.teams.add(other)
    client.force_login(owner)
    client.post(f"/o/teams/{team.pk}/", {"email": stranger.email})
    assert set(stranger.teams.all()) == {team, other}


# The same message is used whether the user does not exist or is already a
# member, so the form cannot be used to probe which emails have accounts.
@pytest.mark.parametrize(
    "email",
    [
        pytest.param("nobody@example.com", id="unknown-user"),
        pytest.param("owner@example.com", id="already-member"),
    ],
)
def test_add_member_validation(client, owner, team, email):
    client.force_login(owner)
    response = client.post(f"/o/teams/{team.pk}/", {"email": email})
    assert response.status_code == 200
    assert f"Could not add {email}." in response.content.decode()


# ---------------------------------------------------------------------------
# TeamMemberRemove POST
# ---------------------------------------------------------------------------


def test_remove_member_success(client, owner, stranger, team):
    stranger.teams.add(team)
    client.force_login(owner)
    assert (
        client.post(f"/o/teams/{team.pk}/members/{stranger.pk}/remove/").status_code
        == 302
    )
    assert not stranger.teams.exists()


def test_remove_member_keeps_other_memberships(client, owner, stranger, team):
    other = Team.objects.create(name="Other Team")
    stranger.teams.add(team, other)
    client.force_login(owner)
    client.post(f"/o/teams/{team.pk}/members/{stranger.pk}/remove/")
    assert set(stranger.teams.all()) == {other}


def test_remove_non_member_is_noop(client, owner, stranger, team):
    client.force_login(owner)
    client.post(f"/o/teams/{team.pk}/members/{stranger.pk}/remove/")
    assert not stranger.teams.exists()


def test_remove_last_member_is_blocked(client, owner, team):
    client.force_login(owner)
    response = client.post(f"/o/teams/{team.pk}/members/{owner.pk}/remove/")
    assert response.status_code == 200
    assert "cannot remove the last member" in response.content.decode()
    assert owner.teams.filter(pk=team.pk).exists()


def test_remove_self_with_other_members_succeeds(client, owner, stranger, team):
    stranger.teams.add(team)
    client.force_login(owner)
    response = client.post(f"/o/teams/{team.pk}/members/{owner.pk}/remove/")
    assert response.status_code == 302
    assert not owner.teams.filter(pk=team.pk).exists()


def test_remove_member_invalid_user_pk(client, owner, team):
    client.force_login(owner)
    assert (
        client.post(
            f"/o/teams/{team.pk}/members/00000000-0000-0000-0000-000000000000/remove/"
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# TeamDomainAdd / TeamDomainRemove POST
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "submitted,stored",
    [
        ("example.com", "example.com"),
        ("  EXAMPLE.COM  ", "example.com"),
    ],
)
def test_add_domain_success(client, owner, team, submitted, stored):
    client.force_login(owner)
    response = client.post(f"/o/teams/{team.pk}/domains/", {"domain": submitted})
    assert response.status_code == 302
    assert list(team.allowed_email_domains.values_list("domain", flat=True)) == [stored]


@pytest.mark.parametrize(
    "domain,error_fragment",
    [
        ("", "Enter a domain."),
        ("example.com", "example.com is already allowed."),
        ("uk", "uk is too broad."),
        ("  COM  ", "com is too broad."),
    ],
)
def test_add_domain_validation(client, owner, team, domain, error_fragment):
    team.allowed_email_domains.create(domain="example.com")
    client.force_login(owner)
    response = client.post(f"/o/teams/{team.pk}/domains/", {"domain": domain})
    assert response.status_code == 200
    assert error_fragment in response.content.decode()


def test_team_detail_shows_domains(client, owner, team):
    team.allowed_email_domains.create(domain="example.com")
    client.force_login(owner)
    assert "example.com" in client.get(f"/o/teams/{team.pk}/").content.decode()


def test_add_domain_form_defaults_to_gov_uk(client, owner, team):
    client.force_login(owner)
    html = client.get(f"/o/teams/{team.pk}/").content.decode()
    assert 'value="gov.uk"' in html


def test_add_domain_error_keeps_submitted_value(client, owner, team):
    client.force_login(owner)
    response = client.post(f"/o/teams/{team.pk}/domains/", {"domain": "uk"})
    assert response.status_code == 200
    # The bad value is kept so it isn't replaced by the gov.uk default.
    assert 'value="uk"' in response.content.decode()


def test_remove_domain_success(client, owner, team):
    allowed_domain = team.allowed_email_domains.create(domain="example.com")
    client.force_login(owner)
    assert (
        client.post(
            f"/o/teams/{team.pk}/domains/{allowed_domain.pk}/remove/"
        ).status_code
        == 302
    )
    assert not team.allowed_email_domains.exists()


def test_remove_domain_invalid_pk(client, owner, team):
    client.force_login(owner)
    assert (
        client.post(
            f"/o/teams/{team.pk}/domains/00000000-0000-0000-0000-000000000000/remove/"
        ).status_code
        == 404
    )
