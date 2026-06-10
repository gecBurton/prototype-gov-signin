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


@pytest.fixture
def other_team_app(db):
    other_team = Team.objects.create(name="Other Team")
    return Application.objects.create(
        name="Other App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="http://localhost/callback",
        team=other_team,
    )


def test_start_page(client):
    response = client.get("/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# App views — GET access (detail, update, delete share the same matrix)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("", id="detail"),
        pytest.param("update/", id="update"),
        pytest.param("delete/", id="delete"),
    ],
)
@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 404), (None, 302)],
    indirect=["authed_client"],
)
def test_app_view_access(authed_client, expected_status, suffix, team, app):
    assert (
        authed_client.get(
            f"/o/teams/{team.pk}/applications/{app.pk}/{suffix}"
        ).status_code
        == expected_status
    )


@pytest.mark.parametrize(
    "url_template",
    [
        pytest.param(
            "/o/teams/{own_team_pk}/applications/{other_app_pk}/",
            id="own-team-other-app",
        ),
        pytest.param(
            "/o/teams/{other_team_pk}/applications/{other_app_pk}/",
            id="other-team-other-app",
        ),
    ],
)
def test_cannot_reach_other_teams_app(
    client, owner, team, other_team_app, url_template
):
    client.force_login(owner)
    url = url_template.format(
        own_team_pk=team.pk,
        other_team_pk=other_team_app.team_id,
        other_app_pk=other_team_app.pk,
    )
    assert client.get(url).status_code == 404


# ---------------------------------------------------------------------------
# App views — POST blocked for non-members (update, delete share the same matrix)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["update/", "delete/"])
@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("stranger", 404), (None, 302)],
    indirect=["authed_client"],
)
def test_app_write_blocked_for_non_member(
    authed_client, expected_status, suffix, team, app
):
    assert (
        authed_client.post(
            f"/o/teams/{team.pk}/applications/{app.pk}/{suffix}"
        ).status_code
        == expected_status
    )


# ---------------------------------------------------------------------------
# ApplicationUpdate
# ---------------------------------------------------------------------------


def test_update_saves_changes(client, owner, team, app):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/{app.pk}/update/",
        {**_FORM_BASE, "name": "Renamed App", "client_id": app.client_id},
    )
    assert response.status_code == 302
    app.refresh_from_db()
    assert app.name == "Renamed App"


# ---------------------------------------------------------------------------
# ApplicationDelete
# ---------------------------------------------------------------------------


def test_delete_removes_application(client, owner, team, app):
    client.force_login(owner)
    pk = app.pk
    assert (
        client.post(f"/o/teams/{team.pk}/applications/{app.pk}/delete/").status_code
        == 302
    )
    assert not Application.objects.filter(pk=pk).exists()


def test_delete_redirects_to_team(client, owner, team, app):
    client.force_login(owner)
    assert (
        client.post(f"/o/teams/{team.pk}/applications/{app.pk}/delete/")["Location"]
        == f"/o/teams/{team.pk}/"
    )


# ---------------------------------------------------------------------------
# ApplicationRegistration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 404), (None, 302)],
    indirect=["authed_client"],
)
def test_registration_page_access(authed_client, expected_status, team):
    assert (
        authed_client.get(f"/o/teams/{team.pk}/applications/register/").status_code
        == expected_status
    )


def test_registration_assigns_team_from_url(client, owner, team):
    client.force_login(owner)
    client.post(
        f"/o/teams/{team.pk}/applications/register/", {**_FORM_BASE, "name": "New App"}
    )
    assert Application.objects.get(name="New App").team_id == team.pk


def test_registration_redirects_to_detail(client, owner, team):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/register/", {**_FORM_BASE, "name": "New App"}
    )
    app = Application.objects.get(name="New App")
    assert response["Location"] == f"/o/teams/{team.pk}/applications/{app.pk}/"


def test_registration_blocked_for_non_member(client, stranger, team):
    client.force_login(stranger)
    response = client.post(
        f"/o/teams/{team.pk}/applications/register/", {**_FORM_BASE, "name": "New App"}
    )
    assert response.status_code == 404
    assert not Application.objects.filter(name="New App").exists()
