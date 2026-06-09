from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Grant a user staff and superuser access to the Django admin"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)
        parser.add_argument("--password", type=str, required=True)

    def handle(self, *args, **options):
        User = get_user_model()
        email = options["email"]
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f"No user found with email: {email}")
        user.is_staff = True
        user.is_superuser = True
        user.set_password(options["password"])
        user.save(update_fields=["is_staff", "is_superuser", "password"])
        self.stdout.write(self.style.SUCCESS(f"Promoted {email} to admin"))
