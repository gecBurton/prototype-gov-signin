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

    The global allow-list is the union of every team's allowed email domains:
    an address may sign in if *some* team would admit its domain. This gates
    account enrolment and every sign-in, ahead of the finer per-application
    check at the authorize endpoint (see views._is_domain_allowed).

    Bootstrap safeguard: when no team has configured any domain the union is
    empty and all addresses are admitted — otherwise a fresh instance could
    never sign anyone in to create the first team and its domains. Once any
    domain exists anywhere, the list is authoritative and other domains are
    refused.
    """
    if not email:
        return False
    suffixes = email_domain_suffixes(email)
    if AllowedEmailDomain.objects.filter(domain__in=suffixes).exists():
        return True
    return not AllowedEmailDomain.objects.exists()
