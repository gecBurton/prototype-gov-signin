from django.conf import settings

from users.models import AllowedEmailDomain

# Domains always permitted to sign in, regardless of team configuration: the
# whole UK central-government estate. Suffix-matched on label boundaries (see
# email_domain_suffixes), so this admits x.gov.uk but never evilgov.uk.
ALWAYS_ALLOWED_DOMAINS = {"gov.uk"}


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

    Admitted if any of:
      * it is an admin (ADMIN_USERS) — the escape hatch that lets the first
        admin sign in to configure the allow-list on a fresh instance, where no
        team domains exist yet;
      * its domain is an always-allowed government domain (.gov.uk);
      * some team's allowed email domains admit it (the union across all teams).

    Otherwise refused — the gate is fail-closed. This is the global check,
    applied ahead of the finer per-application check at the authorize endpoint
    (see views._is_domain_allowed).
    """
    if not email:
        return False
    email = email.lower()
    # Admin escape hatch (bootstrap): admins are always admitted.
    admin_users = settings.ADMIN_USERS
    if admin_users and email in admin_users:
        return True
    suffixes = email_domain_suffixes(email)
    # Always-allowed government domains.
    if suffixes & ALWAYS_ALLOWED_DOMAINS:
        return True
    # Allowed by some team.
    return AllowedEmailDomain.objects.filter(domain__in=suffixes).exists()
