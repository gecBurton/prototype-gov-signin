"""The Django admin authenticates via allauth, not a password form.

Django's admin login was the only password surface in the service and had no
brute-force protection. It now redirects unauthenticated users to allauth's
passwordless, rate-limited login; access still requires ``is_staff``.
"""

from django.contrib.auth import get_user_model
from django.test import override_settings

User = get_user_model()


def test_admin_login_redirects_to_allauth_preserving_next(client, db):
    response = client.get("/admin/login/?next=/admin/users/user/")
    assert response.status_code == 302
    location = response["Location"]
    assert "/accounts/login/" in location
    assert "/admin/users/user/" in location  # the requested page is preserved


def test_admin_login_does_not_serve_a_password_form(client, db):
    # No username/password form is ever rendered — it's always a redirect out.
    response = client.get("/admin/login/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_anonymous_admin_access_funnels_to_allauth(client, db):
    response = client.get("/admin/", follow=True)
    assert any("/accounts/login/" in url for url, _status in response.redirect_chain)


# Render the admin dashboard with plain static storage so the test does not
# depend on a collectstatic manifest (which CI's unit job does not build).
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
def test_staff_can_reach_admin_with_an_allauth_session(client, db):
    staff = User.objects.create_superuser(email="staff@example.com")
    client.force_login(staff)
    assert client.get("/admin/").status_code == 200


def test_authenticated_non_staff_is_funnelled_to_allauth(client, db):
    user = User.objects.create_user(email="plain@example.com")
    client.force_login(user)
    # Signed in but not staff: the login route is a plain redirect out to
    # allauth, never a password form. (Following it as a non-staff user would
    # loop back via admin's own permission check — an accepted tradeoff of the
    # redirect-shadow approach; such a user simply lacks admin access.)
    response = client.get("/admin/login/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
