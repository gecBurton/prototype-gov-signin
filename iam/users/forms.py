from allauth.account.forms import RequestLoginCodeForm
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model

User = get_user_model()


class AutoEnrollRequestLoginCodeForm(RequestLoginCodeForm):
    """Login-by-code that enrols unknown email addresses instead of bouncing them.

    The parent's clean_email owns validation, rate limiting and the user
    lookup, leaving ``self._user`` as None for unknown emails (allauth would
    then send an enumeration-safe "no account" mail). This override only adds
    the missing case: create the account so a login code is sent instead.

    The address is created unverified; allauth marks it verified once the
    emailed code is confirmed.
    """

    def clean_email(self) -> str:
        email = super().clean_email()
        if email and self._user is None:
            user = User(email=email)
            user.set_unusable_password()
            user.save()
            EmailAddress.objects.create(
                user=user, email=email, primary=True, verified=False
            )
            self._user = user
        return email
