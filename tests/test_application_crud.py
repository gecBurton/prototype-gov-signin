import pytest
from django.contrib.auth import get_user_model
from users import hydra

User = get_user_model()

_FORM_BASE = {
    "redirect_uris": "http://localhost/callback",
}


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
            f"/o/teams/{team.pk}/applications/{app.client_id}/{suffix}"
        ).status_code
        == expected_status
    )


@pytest.mark.parametrize(
    "url_template",
    [
        pytest.param(
            "/o/teams/{own_team_pk}/applications/{other_app_id}/",
            id="own-team-other-app",
        ),
        pytest.param(
            "/o/teams/{other_team_pk}/applications/{other_app_id}/",
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
        other_app_id=other_team_app.client_id,
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
            f"/o/teams/{team.pk}/applications/{app.client_id}/{suffix}"
        ).status_code
        == expected_status
    )


# ---------------------------------------------------------------------------
# ApplicationUpdate
# ---------------------------------------------------------------------------


def test_update_saves_changes(client, owner, team, app):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/{app.client_id}/update/",
        {**_FORM_BASE, "name": "Renamed App"},
    )
    assert response.status_code == 302
    refreshed = hydra.get_application(app.client_id)
    assert refreshed.name == "Renamed App"


def test_update_saves_new_fields(client, owner, team, app):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/{app.client_id}/update/",
        {
            **_FORM_BASE,
            "name": app.name,
            "description": "Our service",
            "main_app_url": "https://service.gov.uk",
            "additional_emails": "VIP@example.com  tester@example.com",
        },
    )
    assert response.status_code == 302
    refreshed = hydra.get_application(app.client_id)
    assert refreshed.description == "Our service"
    assert refreshed.main_app_url == "https://service.gov.uk"
    # Stored as a normalised lowercase list.
    assert refreshed.additional_emails == ["vip@example.com", "tester@example.com"]


@pytest.mark.parametrize(
    "posted,expected_skip",
    [({"skip_authorization": "on"}, True), ({}, False)],
)
def test_skip_authorization_checkbox(client, owner, team, app, posted, expected_skip):
    client.force_login(owner)
    client.post(
        f"/o/teams/{team.pk}/applications/{app.client_id}/update/",
        {**_FORM_BASE, "name": app.name, **posted},
    )
    refreshed = hydra.get_application(app.client_id)
    assert refreshed.skip_authorization is expected_skip


def test_update_rejects_invalid_additional_email(client, owner, team, app):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/{app.client_id}/update/",
        {**_FORM_BASE, "name": app.name, "additional_emails": "not-an-email"},
    )
    assert response.status_code == 200  # redisplayed with error
    refreshed = hydra.get_application(app.client_id)
    assert refreshed.additional_emails == []


def test_update_enforces_https_post_logout_redirect(client, owner, team, app):
    # The same https rule the registration form enforces applies on update too:
    # a cleartext post-logout redirect is rejected.
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/{app.client_id}/update/",
        {
            **_FORM_BASE,
            "name": app.name,
            "post_logout_redirect_uris": "http://app.gov.uk/signed-out",
        },
    )
    assert response.status_code == 200  # redisplayed with a validation error
    refreshed = hydra.get_application(app.client_id)
    assert refreshed.post_logout_redirect_uris == []


# ---------------------------------------------------------------------------
# ApplicationDelete
# ---------------------------------------------------------------------------


def test_delete_hides_application(client, owner, team, app):
    # Soft delete: the client stays in Hydra but marked inactive and dropped
    # from the team's active applications.
    client.force_login(owner)
    client_id = app.client_id
    assert (
        client.post(
            f"/o/teams/{team.pk}/applications/{app.client_id}/delete/"
        ).status_code
        == 302
    )
    refreshed = hydra.get_application(client_id)
    assert refreshed is not None
    assert refreshed.is_active is False
    assert client_id not in [a.client_id for a in team.active_applications]


def test_delete_redirects_to_team(client, owner, team, app):
    client.force_login(owner)
    assert (
        client.post(f"/o/teams/{team.pk}/applications/{app.client_id}/delete/")[
            "Location"
        ]
        == f"/o/teams/{team.pk}/"
    )


@pytest.mark.parametrize("suffix", ["", "update/", "delete/"])
def test_hidden_application_not_reachable(client, owner, team, app, suffix):
    # A soft-deleted application is excluded from the management views (404).
    hydra.soft_delete(app.client_id)
    client.force_login(owner)
    url = f"/o/teams/{team.pk}/applications/{app.client_id}/{suffix}"
    assert client.get(url).status_code == 404


def test_hidden_application_not_listed_on_team(client, owner, team, app):
    hydra.soft_delete(app.client_id)
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
    created = [a for a in hydra.list_team_applications(team.pk) if a.name == "New App"]
    assert len(created) == 1


def test_registration_redirects_to_detail(client, owner, team):
    client.force_login(owner)
    response = client.post(
        f"/o/teams/{team.pk}/applications/register/", {**_FORM_BASE, "name": "New App"}
    )
    created = [a for a in hydra.list_team_applications(team.pk) if a.name == "New App"][
        0
    ]
    assert (
        response["Location"] == f"/o/teams/{team.pk}/applications/{created.client_id}/"
    )


def test_registration_blocked_for_non_member(client, stranger, team):
    client.force_login(stranger)
    response = client.post(
        f"/o/teams/{team.pk}/applications/register/", {**_FORM_BASE, "name": "New App"}
    )
    assert response.status_code == 404
    assert not any(a.name == "New App" for a in hydra.list_team_applications(team.pk))


@pytest.mark.parametrize("missing", ["name", "redirect_uris"])
def test_registration_requires_mandatory_fields(client, owner, team, missing):
    client.force_login(owner)
    data = {
        "name": "Req App",
        "redirect_uris": "http://localhost/callback",
    }
    data[missing] = ""
    before = len(hydra.list_team_applications(team.pk))
    response = client.post(f"/o/teams/{team.pk}/applications/register/", data)
    assert response.status_code == 200  # redisplayed with a validation error
    assert len(hydra.list_team_applications(team.pk)) == before


def test_form_groups_fields_into_sections(client, owner, team):
    client.force_login(owner)
    html = client.get(f"/o/teams/{team.pk}/applications/register/").content.decode()
    # Section headings, mandatory fields at the top.
    for heading in ("Required", "Optional details", "Advanced OAuth settings"):
        assert heading in html
    # The sections convey required vs optional, so fields are not marked.
    assert "Description" in html
    assert "(optional)" not in html
    # Locks in a label override.
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
        {"redirect_uris": redirect_uri, "name": "Scheme App"},
    )
    created = any(a.name == "Scheme App" for a in hydra.list_team_applications(team.pk))
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
            "redirect_uris": "https://app.gov.uk/callback",
            "post_logout_redirect_uris": "http://app.gov.uk/signed-out",
            "name": "Logout App",
        },
    )
    assert response.status_code == 200
    assert not any(
        a.name == "Logout App" for a in hydra.list_team_applications(team.pk)
    )


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
        created = [
            a for a in hydra.list_team_applications(team.pk) if a.name == "New App"
        ][0]
        assert created.client_id
    else:
        response = client.post(
            f"/o/teams/{team.pk}/applications/{app.client_id}/regenerate-secret/"
        )
    assert response.status_code == 302

    detail = client.get(response["Location"])
    assert "raw_client_secret" in detail.context

    # The secret is revealed exactly once.
    assert "raw_client_secret" not in client.get(response["Location"]).context
