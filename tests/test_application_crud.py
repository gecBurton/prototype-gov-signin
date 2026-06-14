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


def test_team_is_required(db):
    # Team-less applications are banned: every app must belong to a team.
    with pytest.raises(IntegrityError):
        Application.objects.create(
            name="Orphan App",
            client_type=Application.CLIENT_CONFIDENTIAL,
            redirect_uris="http://localhost/callback",
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


def test_update_saves_new_fields(client, owner, team, app):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/{app.pk}/update/",
        {
            **_FORM_BASE,
            "name": app.name,
            "description": "Our service",
            "main_app_url": "https://service.gov.uk",
            "additional_emails": "VIP@example.com  tester@example.com",
        },
    )
    assert response.status_code == 302
    app.refresh_from_db()
    assert app.description == "Our service"
    assert app.main_app_url == "https://service.gov.uk"
    # Stored normalised to lowercase, space separated.
    assert app.additional_emails == "vip@example.com tester@example.com"


@pytest.mark.parametrize(
    "posted,expected_skip",
    [({"skip_authorization": "on"}, True), ({}, False)],
)
def test_skip_authorization_checkbox(client, owner, team, app, posted, expected_skip):
    client.force_login(owner)
    client.post(
        f"/o/teams/{team.pk}/applications/{app.pk}/update/",
        {**_FORM_BASE, "name": app.name, **posted},
    )
    app.refresh_from_db()
    assert app.skip_authorization is expected_skip


def test_update_rejects_invalid_additional_email(client, owner, team, app):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/{app.pk}/update/",
        {**_FORM_BASE, "name": app.name, "additional_emails": "not-an-email"},
    )
    assert response.status_code == 200  # redisplayed with error
    app.refresh_from_db()
    assert app.additional_emails == ""


# ---------------------------------------------------------------------------
# ApplicationDelete
# ---------------------------------------------------------------------------


def test_delete_hides_application(client, owner, team, app):
    # Soft delete: the row is kept but marked inactive and dropped from the
    # team's active applications.
    client.force_login(owner)
    pk = app.pk
    assert (
        client.post(f"/o/teams/{team.pk}/applications/{app.pk}/delete/").status_code
        == 302
    )
    app.refresh_from_db()
    assert Application.objects.filter(pk=pk).exists()
    assert app.is_active is False
    assert app not in team.active_applications


def test_delete_redirects_to_team(client, owner, team, app):
    client.force_login(owner)
    assert (
        client.post(f"/o/teams/{team.pk}/applications/{app.pk}/delete/")["Location"]
        == f"/o/teams/{team.pk}/"
    )


@pytest.mark.parametrize("suffix", ["", "update/", "delete/"])
def test_hidden_application_not_reachable(client, owner, team, app, suffix):
    # A soft-deleted application is excluded from the management views (404).
    app.is_active = False
    app.save(update_fields=["is_active"])
    client.force_login(owner)
    url = f"/o/teams/{team.pk}/applications/{app.pk}/{suffix}"
    assert client.get(url).status_code == 404


def test_hidden_application_not_listed_on_team(client, owner, team, app):
    app.is_active = False
    app.save(update_fields=["is_active"])
    client.force_login(owner)
    html = client.get(f"/o/teams/{team.pk}/").content.decode()
    assert app.name not in html


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


@pytest.mark.parametrize("missing", ["name", "client_type", "redirect_uris"])
def test_registration_requires_mandatory_fields(client, owner, team, missing):
    client.force_login(owner)
    data = {
        "name": "Req App",
        "client_type": Application.CLIENT_CONFIDENTIAL,
        "redirect_uris": "http://localhost/callback",
    }
    data[missing] = ""
    before = Application.objects.count()
    response = client.post(f"/o/teams/{team.pk}/applications/register/", data)
    assert response.status_code == 200  # redisplayed with a validation error
    assert Application.objects.count() == before


def test_form_groups_fields_into_sections(client, owner, team):
    client.force_login(owner)
    html = client.get(f"/o/teams/{team.pk}/applications/register/").content.decode()
    # Section headings, mandatory fields at the top.
    for heading in ("Required", "Optional details", "Advanced OAuth settings"):
        assert heading in html
    # The sections convey required vs optional, so fields are not marked.
    assert "Description" in html
    assert "(optional)" not in html
    # Locks in a label override from Meta.labels.
    assert "Redirect URIs" in html


def test_form_renders_every_field(client, owner, team):
    # The sectioned template lists fields by name, so a field added to the form
    # but not the template would silently go missing. Assert each one renders.
    client.force_login(owner)
    response = client.get(f"/o/teams/{team.pk}/applications/register/")
    html = response.content.decode()
    for field in response.context["form"].visible_fields():
        assert f'id="{field.id_for_label}"' in html, f"{field.name} not rendered"


@pytest.mark.parametrize(
    "redirect_uri,allowed",
    [
        ("https://app.example.gov.uk/callback", True),
        ("http://localhost:3000/callback", True),  # loopback exception
        ("http://127.0.0.1/callback", True),  # loopback exception
        ("http://app.example.gov.uk/callback", False),  # cleartext, non-loopback
    ],
)
def test_registration_enforces_https_redirect(
    client, owner, team, redirect_uri, allowed
):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/register/",
        {
            "client_type": Application.CLIENT_CONFIDENTIAL,
            "redirect_uris": redirect_uri,
            "name": "Scheme App",
        },
    )
    created = Application.objects.filter(name="Scheme App").exists()
    if allowed:
        assert response.status_code == 302
        assert created
    else:
        # Form redisplayed with a validation error; nothing saved.
        assert response.status_code == 200
        assert not created


def test_registration_enforces_https_post_logout_redirect(client, owner, team):
    # The https rule applies to post-logout redirect URIs too.
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/register/",
        {
            "client_type": Application.CLIENT_CONFIDENTIAL,
            "redirect_uris": "https://app.gov.uk/callback",
            "post_logout_redirect_uris": "http://app.gov.uk/signed-out",
            "name": "Logout App",
        },
    )
    assert response.status_code == 200
    assert not Application.objects.filter(name="Logout App").exists()


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
