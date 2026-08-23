from django.conf import settings

from users.hydra import list_all_active_applications
from users.models import AllowedEmailDomain


def email_domain_suffixes(email: str) -> set[str]:
    """The label-boundary suffixes of an email's domain.

    ``a@deep.nested.gov.uk`` → ``{deep.nested.gov.uk, nested.gov.uk, gov.uk,
    uk}``. A domain admits the address when one of the allowed domains exactly
    equals one of these, so cabinetoffice.gov.uk admits @x.cabinetoffice.gov.uk
    but evilcabinetoffice.gov.uk never matches cabinetoffice.gov.uk.
    """
    labels = email.rsplit("@", 1)[-1].lower().split(".")
    return {".".join(labels[i:]) for i in range(len(labels))}


def is_signin_domain_allowed(email: str) -> bool:
    """Whether an address may sign in to this service at all.

    Admitted if any of: it's an admin (ADMIN_USERS — the bootstrap escape
    hatch); its domain is .gov.uk; some team's allowed domains admit it; or
    it's individually listed in an active application's additional_emails.
    Otherwise refused (fail-closed). This is the global check, ahead of the
    finer per-application check at authorize time (users.views._is_domain_allowed).
    """
    if not email:
        return False
    email = email.lower()
    admin_users = settings.ADMIN_USERS
    if admin_users and email in admin_users:
        return True
    suffixes = email_domain_suffixes(email)
    if "gov.uk" in suffixes:
        return True
    if AllowedEmailDomain.objects.filter(domain__in=suffixes).exists():
        return True
    # additional_emails is normalised lowercase in users.hydra.
    return any(
        email in application.additional_email_list
        for application in list_all_active_applications()
    )
