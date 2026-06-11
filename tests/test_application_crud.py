import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.db import IntegrityError
from oauth2_provider.models import AbstractApplication, get_application_model
from users.models import Team

User = get_user_model()
Application = get_application_model()

_FORM_BASE = {
    "client_type": Application.CLIENT_CONFIDENTIAL,
    "redirect_uris": "http://localhost/callback",
}


@pytest.fixture
def other_team_app(db):
    other_team = Team.objects.create(name="Other Team")
    return Application.objects.create(
        name="Other App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        redirect_uris="http://localhost/callback",
        team=other_team,
    )


def test_start_page(client):
    response = client.get("/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Application model — only authorization-code/RS256/hashed secrets may be stored
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("authorization_grant_type", grant)
        for grant, _ in AbstractApplication.GRANT_TYPES
        if grant != Application.GRANT_AUTHORIZATION_CODE
    ]
    + [
        ("algorithm", Application.HS256_ALGORITHM),
        ("algorithm", Application.NO_ALGORITHM),
        ("hash_client_secret", False),
    ],
)
def test_disallowed_application_settings_rejected(db, team, field, value):
    with pytest.raises(IntegrityError):
        Application.objects.create(
            name="Bad App",
            client_type=Application.CLIENT_CONFIDENTIAL,
            redirect_uris="http://localhost/callback",
            team=team,
            **{field: value},
        )


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


@pytest.mark.parametrize("suffix", ["update/", "delete/", "regenerate-secret/"])
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
        {**_FORM_BASE, "name": "Renamed App"},
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


# ---------------------------------------------------------------------------
# Server-issued credentials
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["register", "regenerate"])
def test_issued_secret_is_valid_and_shown_once(client, owner, team, app, action):
    client.force_login(owner)
    if action == "register":
        response = client.post(
            f"/o/teams/{team.pk}/applications/register/",
            {**_FORM_BASE, "name": "New App"},
        )
        app = Application.objects.get(name="New App")
        assert app.client_id
    else:
        old_hash = app.client_secret
        response = client.post(
            f"/o/teams/{team.pk}/applications/{app.pk}/regenerate-secret/"
        )
        app.refresh_from_db()
        assert app.client_secret != old_hash
    assert response.status_code == 302

    detail = client.get(response["Location"])
    assert check_password(detail.context["raw_client_secret"], app.client_secret)

    # The secret is revealed exactly once.
    assert "raw_client_secret" not in client.get(response["Location"]).context
