from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from oauth2_provider.models import AbstractApplication


class User(AbstractUser):
    pass


class Application(AbstractApplication):
    owners = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="owned_applications",
    )
    allowed_email_domains = models.TextField(
        blank=True,
        default="",
        help_text="One domain per line (e.g. example.com). Leave blank to allow all users.",
    )

    class Meta(AbstractApplication.Meta):
        swappable = "OAUTH2_PROVIDER_APPLICATION_MODEL"
