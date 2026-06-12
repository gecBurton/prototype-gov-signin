"""The service has no passwords.

Accounts authenticate via email login-code or Google and are created with an
unusable password. There is no password login, no password management, and no
password-checking auth backend.
"""

import pytest
from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

User = get_user_model()


# ---------------------------------------------------------------------------
# Accounts never have a usable password
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ["create_user", "create_superuser"])
def test_created_accounts_have_no_usable_password(db, factory):
    user = getattr(User.objects, factory)(email=f"{factory}@example.com")
    assert not user.has_usable_password()


def test_password_argument_is_ignored(db):
    user = User.objects.create_user(email="ignored@example.com", password="hunter2")
    assert not user.has_usable_password()


# ---------------------------------------------------------------------------
# No password-checking backend; allauth's backend still provides admin perms
# ---------------------------------------------------------------------------


def test_only_allauth_backend_is_configured():
    assert settings.AUTHENTICATION_BACKENDS == [
        "allauth.account.auth_backends.AuthenticationBackend"
    ]


def test_superuser_keeps_admin_permissions_without_modelbackend(db):
    admin = User.objects.create_superuser(email="su@example.com")
    # Permission lookups must still resolve (allauth's backend subclasses
    # ModelBackend), and is_superuser short-circuits to True.
    assert admin.has_perm("users.change_user")


# ---------------------------------------------------------------------------
# Password management endpoints are closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/accounts/password/reset/",
        "/accounts/password/change/",
        "/accounts/password/set/",
    ],
)
def test_password_endpoints_are_closed(client, db, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


# ---------------------------------------------------------------------------
# promote_user is passwordless
# ---------------------------------------------------------------------------


def test_promote_user_makes_admin_without_a_password(db):
    User.objects.create_user(email="admin@dept.gov.uk")

    call_command("promote_user", "admin@dept.gov.uk")

    user = User.objects.get(email="admin@dept.gov.uk")
    assert user.is_staff and user.is_superuser
    assert not user.has_usable_password()
    assert EmailAddress.objects.filter(
        user=user, email="admin@dept.gov.uk", verified=True
    ).exists()


def test_promote_user_rejects_a_password_option(db):
    User.objects.create_user(email="np@dept.gov.uk")
    with pytest.raises(Exception):
        call_command("promote_user", "np@dept.gov.uk", "--password", "secret")
