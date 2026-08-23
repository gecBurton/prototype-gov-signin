from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.db.models import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from users import hydra
from users.models import Team


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
    # settings.ADMIN_USERS is already lowercased at parse time.
    should_be_admin = user.email.lower() in admin_users
    if user.is_staff != should_be_admin or user.is_superuser != should_be_admin:
        user.is_staff = should_be_admin
        user.is_superuser = should_be_admin
        user.save(update_fields=["is_staff", "is_superuser"])


@receiver(pre_delete, sender=Team)
def block_team_deletion_with_applications(sender, instance, **kwargs):
    """Refuse to delete a team that still owns applications in Hydra.

    Previously enforced by a database PROTECT constraint on Application.team
    (django-oauth-toolkit's AbstractApplication). Applications now live in
    Hydra, not this database, so there is no foreign key for the database to
    enforce — this signal is the replacement, so a team's domain restrictions
    (and the applications that depend on them) can never be silently orphaned
    by deleting the team out from under them.
    """
    if hydra.list_team_applications(instance.pk, include_inactive=True):
        raise ProtectedError(
            f"Cannot delete team {instance} while it still owns applications "
            "in Hydra. Move or remove its applications first.",
            [],
        )
