import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from users import hydra


class Team(models.Model):
    """A group of users who jointly own OAuth applications.

    Applications aren't a Django model: each is a Hydra client owned by
    this team's id. See users.hydra.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)

    @property
    def active_applications(self):
        """The team's applications that have not been soft-deleted."""
        return hydra.list_team_applications(self.id)

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    """Manager for the username-less User model; creates users by email."""

    use_in_migrations = True

    def _create_user(self, email, **extra_fields):
        if not email:
            raise ValueError("The email must be set")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        # No passwords: every account authenticates via email code or Google.
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


class SignInEvent(models.Model):
    """One row per successful sign-in: a user authorising an application.

    Applications live in Hydra, not this database, so the application is
    referenced by its Hydra client_id and a denormalised name/team snapshot
    rather than a foreign key — history survives even if the client is
    later deleted from Hydra.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, related_name="sign_in_events"
    )
    application_client_id = models.CharField(max_length=255, db_index=True)
    application_name = models.CharField(max_length=255)
    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, related_name="sign_in_events"
    )
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.user} → {self.application_name} at {self.created:%Y-%m-%d %H:%M}"
