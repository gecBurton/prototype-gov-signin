from urllib.parse import urlparse

from allauth.account.forms import RequestLoginCodeForm
from allauth.account.models import EmailAddress
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from users.domains import is_signin_domain_allowed

User = get_user_model()

# http is only safe for loopback redirect URIs (a developer's own machine, per
# RFC 8252); anywhere else a cleartext redirect can leak the authorization code.
_LOOPBACK_REDIRECT_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validate_https_uris(value, field_label):
    """Require https for a whitespace-separated list of URIs.

    http is allowed only for loopback hosts (localhost, during development).
    Applies to redirect_uris and post_logout_redirect_uris alike — a cleartext
    endpoint could leak an authorization code or a logout redirect.
    """
    for uri in value.split():
        parsed = urlparse(uri)
        if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_REDIRECT_HOSTS:
            raise ValidationError(
                f"{uri} must use https. http is only allowed for loopback "
                "addresses (localhost) during development."
            )


class ApplicationForm(forms.Form):
    """Create/update form for an OAuth application (an Ory Hydra client).

    No backing Django model — an Application is a Hydra client, fetched and
    saved via users.hydra.
    """

    name = forms.CharField(label="Name", max_length=255)
    redirect_uris = forms.CharField(
        label="Redirect URIs",
        widget=forms.Textarea,
        help_text="One or more URIs, space separated.",
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="What this application is for. Shown to the team, not to end users.",
    )
    main_app_url = forms.URLField(
        required=False,
        label="Main app URL",
        help_text="The application's home page, e.g. https://my-service.gov.uk.",
    )
    additional_emails = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text=(
            "Extra email addresses allowed to sign in to this application, "
            "space separated, regardless of the team's allowed domains."
        ),
    )
    post_logout_redirect_uris = forms.CharField(
        required=False,
        label="Post-logout redirect URIs",
        widget=forms.Textarea,
    )
    allowed_origins = forms.CharField(
        required=False,
        widget=forms.Textarea,
        help_text="Origins allowed to make CORS requests, space separated.",
    )
    skip_authorization = forms.BooleanField(
        required=False,
        label="Skip the consent screen",
        help_text=(
            "Tick to send users straight through without showing a consent "
            "screen the first time they sign in to this application."
        ),
    )
    listed = forms.BooleanField(
        required=False,
        initial=True,
        label="Show in the applications directory",
    )

    def __init__(self, *args, application=None, **kwargs):
        """``application`` is a users.hydra.Application to seed initial values from."""
        if application is not None and "initial" not in kwargs:
            kwargs["initial"] = {
                "name": application.name,
                "redirect_uris": " ".join(application.redirect_uris),
                "description": application.description,
                "main_app_url": application.main_app_url,
                "additional_emails": " ".join(application.additional_emails),
                "post_logout_redirect_uris": " ".join(
                    application.post_logout_redirect_uris
                ),
                "allowed_origins": " ".join(application.allowed_cors_origins),
                "skip_authorization": application.skip_authorization,
                "listed": application.listed,
            }
        super().__init__(*args, **kwargs)

    def clean_additional_emails(self):
        emails = []
        for token in self.cleaned_data["additional_emails"].split():
            email = token.lower()
            try:
                validate_email(email)
            except ValidationError:
                raise ValidationError(f"{token} is not a valid email address.")
            emails.append(email)
        return emails

    def clean_redirect_uris(self):
        value = self.cleaned_data["redirect_uris"]
        _validate_https_uris(value, "Redirect URIs")
        return value

    def clean_post_logout_redirect_uris(self):
        value = self.cleaned_data["post_logout_redirect_uris"]
        _validate_https_uris(value, "Post-logout redirect URIs")
        return value

    def to_hydra_kwargs(self) -> dict:
        """The cleaned data, shaped for users.hydra.create_application/update_application."""
        data = self.cleaned_data
        return {
            "name": data["name"],
            "redirect_uris": data["redirect_uris"].split(),
            "post_logout_redirect_uris": data["post_logout_redirect_uris"].split(),
            "allowed_cors_origins": data["allowed_origins"].split(),
            "skip_authorization": data["skip_authorization"],
            "description": data["description"],
            "main_app_url": data["main_app_url"],
            "additional_emails": data["additional_emails"],
            "listed": data["listed"],
        }


class AutoEnrollRequestLoginCodeForm(RequestLoginCodeForm):
    """Login-by-code that enrols unknown email addresses instead of bouncing them.

    Makes the account exist *before* delegating to allauth, so its own
    lookup finds the user and sends a code — no need to touch allauth's
    private ``self._user``. The address is created unverified; allauth marks
    it verified once the emailed code is confirmed.
    """

    def clean_email(self) -> str:
        email = self.cleaned_data.get("email")
        if email:
            # Global sign-in gate: refuse domains no team would admit, before
            # creating any account row (see users.domains.is_signin_domain_allowed).
            # Applies to returning users too — this gates signing in, not just
            # first enrolment.
            if not is_signin_domain_allowed(email):
                raise ValidationError("Your email is not allowed to sign in.")
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
