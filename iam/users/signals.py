from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def sync_admin_status(sender, request, user, **kwargs):
    """Make settings.ADMIN_USERS the source of truth for admin access.

    On every login, grant staff + superuser to users whose email is listed and
    revoke it from anyone who is no longer listed. When ADMIN_USERS is unset
    (None) the mechanism is inactive and existing flags are left as-is.
    """
    admin_users = settings.ADMIN_USERS
    if admin_users is None:
        return
    should_be_admin = user.email.lower() in {email.lower() for email in admin_users}
    if user.is_staff != should_be_admin or user.is_superuser != should_be_admin:
        user.is_staff = should_be_admin
        user.is_superuser = should_be_admin
        user.save(update_fields=["is_staff", "is_superuser"])
