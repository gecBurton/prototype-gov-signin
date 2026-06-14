from allauth.account.forms import RequestLoginCodeForm
from allauth.account.models import EmailAddress
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from oauth2_provider.models import get_application_model

User = get_user_model()


class ApplicationForm(forms.ModelForm):
    """Create/update form for an OAuth application."""

    class Meta:
        model = get_application_model()
        fields = (
            "name",
            "client_type",
            "redirect_uris",
            "description",
            "main_app_url",
            "additional_emails",
            "post_logout_redirect_uris",
            "allowed_origins",
            "skip_authorization",
            "listed",
        )
        # Only override the labels Django would otherwise mis-case or where the
        # model name reads poorly; the rest fall back to the model fields'
        # verbose names.
        labels = {
            "redirect_uris": "Redirect URIs",
            "main_app_url": "Main app URL",
            "post_logout_redirect_uris": "Post-logout redirect URIs",
            "skip_authorization": "Skip the consent screen",
            "listed": "Show in the applications directory",
        }
        help_texts = {
            "skip_authorization": (
                "Tick to send users straight through without showing a consent "
                "screen the first time they sign in to this application."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # name and redirect_uris are blank=True on the model (the toolkit allows
        # admin-seeded clients without them) but a team filling in this form must
        # provide them, so they are required here.
        self.fields["name"].required = True
        self.fields["redirect_uris"].required = True

    def clean_additional_emails(self):
        emails = []
        for token in self.cleaned_data["additional_emails"].split():
            email = token.lower()
            try:
                validate_email(email)
            except ValidationError:
                raise ValidationError(f"{token} is not a valid email address.")
            emails.append(email)
        return " ".join(emails)


class AutoEnrollRequestLoginCodeForm(RequestLoginCodeForm):
    """Login-by-code that enrols unknown email addresses instead of bouncing them.

    The parent's clean_email owns validation, rate limiting and the user
    lookup, leaving ``self._user`` as None for unknown emails (allauth would
    then send an enumeration-safe "no account" mail). This override adds the
    missing case: create the account so a login code is sent instead, and
    ensure an EmailAddress row exists for the account (backfilling any
    pre-existing user that lacks one).

    The address is created unverified; allauth marks it verified once the
    emailed code is confirmed, which is what satisfies
    ACCOUNT_EMAIL_VERIFICATION="mandatory".
    """

    def clean_email(self) -> str:
        email = super().clean_email()
        if not email:
            return email
        if self._user is None:
            user = User(email=email)
            user.set_unusable_password()
            user.save()
            self._user = user
        # Ensure an EmailAddress row exists so confirming the code can mark it
        # verified. Without one, login-by-code cannot verify the address and
        # ACCOUNT_EMAIL_VERIFICATION="mandatory" would refuse the login — this
        # backfills users who never went through enrolment (e.g. seed- or
        # admin-created accounts). The address is created unverified; the
        # confirmed code is what verifies it.
        EmailAddress.objects.get_or_create(
            user=self._user,
            email=email,
            defaults={"primary": True, "verified": False},
        )
        return email
