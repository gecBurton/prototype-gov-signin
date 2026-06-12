from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Grant a user staff and superuser access to the Django admin"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str)
        # The admin authenticates via allauth (email code / Google), so a
        # password is not needed to sign in. Kept as an optional escape hatch.
        parser.add_argument("--password", type=str, default=None)

    def handle(self, *args, **options):
        User = get_user_model()
        email = options["email"]
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(
                f"No user found with email: {email}. Have them sign in once "
                "(which creates the account) before promoting."
            )
        user.is_staff = True
        user.is_superuser = True
        if options["password"]:
            user.set_password(options["password"])
        user.save()
        # The admin logs in via allauth, which needs a verified EmailAddress.
        EmailAddress.objects.update_or_create(
            user=user,
            email=email,
            defaults={"primary": True, "verified": True},
        )
        self.stdout.write(self.style.SUCCESS(f"Promoted {email} to admin"))
