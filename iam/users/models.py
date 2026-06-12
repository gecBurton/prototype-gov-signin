import uuid
from urllib.parse import urlparse

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from oauth2_provider.models import AbstractApplication

# http is only safe for loopback redirect URIs (a developer's own machine, per
# RFC 8252); anywhere else a cleartext redirect can leak the authorization code.
_LOOPBACK_REDIRECT_HOSTS = {"localhost", "127.0.0.1", "::1"}


class Team(models.Model):
    """A group of users who jointly own OAuth applications."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    """Manager for the username-less User model; creates users by email."""

    use_in_migrations = True

    def _create_user(self, email, **extra_fields):
        if not email:
            raise ValueError("The email must be set")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        # This service has no passwords: every account authenticates via email
        # login-code or Google. Any password argument (e.g. from
        # createsuperuser) is intentionally ignored.
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, **extra_fields)


class User(AbstractUser):
    """A user identified by email address; there is no username field."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField("email address", unique=True)
    teams = models.ManyToManyField(
        Team,
        through="Membership",
        blank=True,
        related_name="members",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()


class Membership(models.Model):
    """Joins a user to a team."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "team"], name="unique_user_team")
        ]

    def __str__(self):
        return f"{self.user} in {self.team}"


class AllowedEmailDomain(models.Model):
    """An email domain whose users may sign in to a team's applications.

    Matching is by suffix: allowing cabinetoffice.gov.uk also admits
    digital.cabinetoffice.gov.uk. A team with no domains allows all users.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="allowed_email_domains"
    )
    domain = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "domain"], name="unique_team_domain"
            )
        ]

    def save(self, *args, **kwargs):
        self.domain = self.domain.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.domain


class Application(AbstractApplication):
    """An OAuth2/OIDC client, owned and managed by a team."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # A team-less application (admin-created, e.g. the demo Grafana client)
    # allows all users, so deleting a team must not silently drop its apps'
    # domain restrictions: PROTECT forces the apps to be deleted (or moved)
    # first.
    team = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="applications",
    )
    # Only the authorization-code grant is supported: implicit, password and
    # hybrid are deprecated (removed in OAuth 2.1). If we ever need
    # machine-to-machine clients, client-credentials may have to be re-allowed.
    authorization_grant_type = models.CharField(
        max_length=44,
        choices=[(AbstractApplication.GRANT_AUTHORIZATION_CODE, "Authorization code")],
        default=AbstractApplication.GRANT_AUTHORIZATION_CODE,
    )
    algorithm = models.CharField(
        max_length=5,
        choices=[(AbstractApplication.RS256_ALGORITHM, "RSA with SHA-2 256")],
        default=AbstractApplication.RS256_ALGORITHM,
    )
    # Client secrets are always stored hashed; a lost secret is replaced,
    # never recovered.
    hash_client_secret = models.BooleanField(default=True, editable=False)

    def clean(self):
        super().clean()
        # Require https for redirect URIs, allowing http only for loopback
        # hosts. The parent permits http anywhere; tighten it so an
        # authorization code can never be sent to a cleartext, non-local
        # endpoint. Enforced on the registration/update form (which validates);
        # ORM-seeded apps such as the demo bypass this, and the demo's
        # http://localhost redirect is loopback anyway.
        for uri in self.redirect_uris.split():
            parsed = urlparse(uri)
            if (
                parsed.scheme == "http"
                and parsed.hostname not in _LOOPBACK_REDIRECT_HOSTS
            ):
                raise ValidationError(
                    {
                        "redirect_uris": (
                            f"{uri} must use https. http is only allowed for "
                            "loopback addresses (localhost) during development."
                        )
                    }
                )

    class Meta(AbstractApplication.Meta):
        swappable = "OAUTH2_PROVIDER_APPLICATION_MODEL"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE
                ),
                name="application_grant_type_authorization_code",
            ),
            models.CheckConstraint(
                condition=models.Q(algorithm=AbstractApplication.RS256_ALGORITHM),
                name="application_algorithm_rs256",
            ),
            models.CheckConstraint(
                condition=models.Q(hash_client_secret=True),
                name="application_hash_client_secret",
            ),
        ]
