import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model

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


def test_start_page(client):
    response = client.get("/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# ApplicationList
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 200), (None, 302)],
    indirect=["authed_client"],
)
def test_list_access(authed_client, expected_status, app):
    assert authed_client.get("/o/applications/").status_code == expected_status


def test_list_shows_only_team_apps(client, owner, stranger, app):
    client.force_login(owner)
    assert app.name in client.get("/o/applications/").content.decode()
    client.force_login(stranger)
    assert app.name not in client.get("/o/applications/").content.decode()


# ---------------------------------------------------------------------------
# App views — GET access (detail, update, delete share the same matrix)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "suffix",
    [pytest.param("", id="detail"), pytest.param("update/", id="update"), pytest.param("delete/", id="delete")],
)
@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 404), (None, 302)],
    indirect=["authed_client"],
)
def test_app_view_access(authed_client, expected_status, suffix, app):
    assert authed_client.get(f"/o/applications/{app.pk}/{suffix}").status_code == expected_status


# ---------------------------------------------------------------------------
# App views — POST blocked for non-members (update, delete share the same matrix)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["update/", "delete/"])
@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("stranger", 404), (None, 302)],
    indirect=["authed_client"],
)
def test_app_write_blocked_for_non_member(authed_client, expected_status, suffix, app):
    assert authed_client.post(f"/o/applications/{app.pk}/{suffix}").status_code == expected_status


# ---------------------------------------------------------------------------
# ApplicationUpdate
# ---------------------------------------------------------------------------


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


def test_delete_removes_application(client, owner, app):
    client.force_login(owner)
    pk = app.pk
    assert client.post(f"/o/applications/{app.pk}/delete/").status_code == 302
    assert not Application.objects.filter(pk=pk).exists()


def test_delete_redirects_to_list(client, owner, app):
    client.force_login(owner)
    assert client.post(f"/o/applications/{app.pk}/delete/")["Location"] == "/o/applications/"


# ---------------------------------------------------------------------------
# ApplicationRegistration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), ("stranger", 403), (None, 302)],
    indirect=["authed_client"],
)
def test_registration_page_access(authed_client, expected_status):
    assert authed_client.get("/o/applications/register/").status_code == expected_status


def test_registration_assigns_creators_team(client, owner):
    client.force_login(owner)
    client.post("/o/applications/register/", {**_FORM_BASE, "name": "New App"})
    assert Application.objects.get(name="New App").team_id == owner.team_id


def test_registration_redirects_to_detail(client, owner):
    client.force_login(owner)
    response = client.post("/o/applications/register/", {**_FORM_BASE, "name": "New App"})
    app = Application.objects.get(name="New App")
    assert response["Location"] == f"/o/applications/{app.pk}/"
