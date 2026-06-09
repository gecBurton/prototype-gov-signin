import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model

User = get_user_model()
Application = get_application_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="owner", email="owner@example.com")


@pytest.fixture
def co_owner(db):
    return User.objects.create_user(username="co_owner", email="co-owner@example.com")


@pytest.fixture
def stranger(db):
    return User.objects.create_user(username="stranger", email="stranger@example.com")


@pytest.fixture
def app(owner, co_owner):
    application = Application.objects.create(
        name="Test App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
    )
    application.owners.set([owner, co_owner])
    return application


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
def test_add_owner_requires_ownership(
    request, client, user_fixture, expected_status, app, co_owner
):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.post(
        f"/o/applications/{app.pk}/owners/",
        {"email": co_owner.email},
    )
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "user_fixture,expected_status",
    [
        ("stranger", 404),
        (None, 302),
    ],
)
def test_remove_owner_requires_ownership(
    request, client, user_fixture, expected_status, app, co_owner
):
    if user_fixture:
        client.force_login(request.getfixturevalue(user_fixture))
    response = client.post(f"/o/applications/{app.pk}/owners/{co_owner.pk}/remove/")
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# Adding owners
# ---------------------------------------------------------------------------


def test_add_owner_success(client, owner, stranger, app):
    client.force_login(owner)
    response = client.post(
        f"/o/applications/{app.pk}/owners/",
        {"email": stranger.email},
    )
    assert response.status_code == 302
    assert app.owners.filter(pk=stranger.pk).exists()


@pytest.mark.parametrize(
    "email,error_fragment",
    [
        ("nobody@example.com", "No user found with email nobody@example.com"),
        ("owner@example.com", "owner@example.com is already an owner"),
    ],
)
def test_add_owner_validation(client, owner, app, email, error_fragment):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/", {"email": email})
    assert response.status_code == 200
    assert error_fragment in response.content.decode()
    assert app.owners.count() == 2  # unchanged


# ---------------------------------------------------------------------------
# Removing owners
# ---------------------------------------------------------------------------


def test_remove_owner_success(client, owner, co_owner, app):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/{co_owner.pk}/remove/")
    assert response.status_code == 302
    assert not app.owners.filter(pk=co_owner.pk).exists()
    assert app.owners.filter(pk=owner.pk).exists()


def test_remove_last_owner_blocked(client, owner, app):
    app.owners.set([owner])
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/{owner.pk}/remove/")
    assert response.status_code == 302
    assert app.owners.count() == 1


def test_remove_last_owner_redirects_to_owners_page(client, owner, app):
    app.owners.set([owner])
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/{owner.pk}/remove/")
    assert response["Location"] == f"/o/applications/{app.pk}/owners/"


def test_remove_owner_invalid_user_pk(client, owner, app):
    client.force_login(owner)
    response = client.post(f"/o/applications/{app.pk}/owners/99999/remove/")
    assert response.status_code == 404
