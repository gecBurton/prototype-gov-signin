from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from oauth2_provider.models import get_application_model

User = get_user_model()
Application = get_application_model()


class Command(BaseCommand):
    help = "Create demo OAuth2 applications and users"

    def handle(self, *args, **options):
        self._create_user("demo@example.com")
        self._create_app(
            client_id="grafana",
            name="Grafana",
            redirect_uris="http://localhost:3000/login/generic_oauth",
            client_secret="grafana-secret",
        )

    def _create_user(self, email):
        username = email.split("@")[0]
        user, created = User.objects.get_or_create(
            email=email,
            defaults={"username": username},
        )
        if created:
            user.set_unusable_password()
            user.save()
        action = "Created" if created else "Found"
        self.stdout.write(self.style.SUCCESS(f"{action} user: {email}"))

    def _create_app(self, *, client_id, name, redirect_uris, client_secret):
        app, created = Application.objects.update_or_create(
            client_id=client_id,
            defaults={
                "name": name,
                "client_type": Application.CLIENT_CONFIDENTIAL,
                "authorization_grant_type": Application.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": redirect_uris,
                "client_secret": client_secret,
                "algorithm": "RS256",
                "skip_authorization": True,
            },
        )
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} OAuth2 app: {name}"))
