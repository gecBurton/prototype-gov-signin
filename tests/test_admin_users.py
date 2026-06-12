"""ADMIN_USERS is the source of truth for admin access.

On login, users listed in settings.ADMIN_USERS are granted staff + superuser,
and anyone no longer listed is demoted. When ADMIN_USERS is None the mechanism
is inactive.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.test import override_settings

User = get_user_model()


def _login(user):
    """Fire the login signal the way an allauth login does."""
    user_logged_in.send(sender=user.__class__, request=None, user=user)


@override_settings(ADMIN_USERS=["admin@dept.gov.uk"])
def test_listed_user_is_promoted_on_login(db):
    user = User.objects.create_user(email="admin@dept.gov.uk")
    assert not user.is_staff

    _login(user)

    user.refresh_from_db()
    assert user.is_staff and user.is_superuser


@override_settings(ADMIN_USERS=["someone-else@dept.gov.uk"])
def test_unlisted_user_is_demoted_on_login(db):
    # An existing admin who is no longer listed loses access on next login.
    user = User.objects.create_superuser(email="ex-admin@dept.gov.uk")
    assert user.is_staff and user.is_superuser

    _login(user)

    user.refresh_from_db()
    assert not user.is_staff and not user.is_superuser


@override_settings(ADMIN_USERS=["ADMIN@DEPT.GOV.UK"])
def test_match_is_case_insensitive(db):
    user = User.objects.create_user(email="admin@dept.gov.uk")
    _login(user)
    user.refresh_from_db()
    assert user.is_staff


@override_settings(ADMIN_USERS=None)
def test_unset_admin_users_leaves_flags_untouched(db):
    admin = User.objects.create_superuser(email="keep@dept.gov.uk")
    plain = User.objects.create_user(email="plain@dept.gov.uk")

    _login(admin)
    _login(plain)

    admin.refresh_from_db()
    plain.refresh_from_db()
    assert admin.is_staff and admin.is_superuser  # not demoted
    assert not plain.is_staff  # not promoted


@override_settings(ADMIN_USERS=["admin@dept.gov.uk"])
@pytest.mark.parametrize("already_admin", [True, False])
def test_no_write_when_status_already_correct(db, already_admin):
    # A no-op login (status already matches) must not error.
    if already_admin:
        user = User.objects.create_superuser(email="admin@dept.gov.uk")
    else:
        user = User.objects.create_user(email="admin@dept.gov.uk")
        # not listed-as-admin mismatch handled by other tests; here listed+admin
    _login(user)
    user.refresh_from_db()
    assert user.is_staff is True
