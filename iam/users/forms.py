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
        )
        # Only override the labels Django would otherwise mis-case or where the
        # model name reads poorly; the rest fall back to the model fields'
        # verbose names.
        labels = {
            "redirect_uris": "Redirect URIs",
            "main_app_url": "Main app URL",
            "post_logout_redirect_uris": "Post-logout redirect URIs",
            "skip_authorization": "Skip the consent screen",
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

    By default allauth's clean_email finds no account for an unknown address,
    leaving it to send an enumeration-safe "no account" mail. We make the
    account exist *before* delegating to allauth: its own lookup then finds the
    user and sends a login code, with no need to touch allauth's private
    ``self._user``. The only coupling left is the supported one — subclassing
    the configured RequestLoginCodeForm and calling super().

    The address is created unverified; allauth marks it verified once the
    emailed code is confirmed, which is what satisfies
    ACCOUNT_EMAIL_VERIFICATION="mandatory". An EmailAddress row is also ensured
    for any pre-existing user that lacks one (e.g. seed- or admin-created
    accounts), so confirming the code can verify it.

    Field validation has already run by the time clean_email is called, so
    self.cleaned_data["email"] is a valid, normalised address. Creating the
    account here (before super()'s rate-limit check) means an address rejected
    by the per-IP limit can still leave an unverified, unusable-password row;
    that is an accepted trade-off (see ACCOUNT_RATE_LIMITS in settings.py).
    """

    def clean_email(self) -> str:
        email = self.cleaned_data.get("email")
        if email:
            user, created = User.objects.get_or_create(email=email)
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
            EmailAddress.objects.get_or_create(
                user=user,
                email=email,
                defaults={"primary": True, "verified": False},
            )
        # The account now exists, so allauth's lookup sets self._user itself.
        return super().clean_email()
