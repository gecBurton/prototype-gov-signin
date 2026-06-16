from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect

from users.domains import is_signin_domain_allowed


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Apply the global sign-in domain allow-list to social (Google) logins.

    Without this, Google would bypass the login-code form's domain check: any
    Google address could enrol regardless of the allowed domains. pre_social_login
    runs before the account is created or connected — for brand-new sign-ups and
    for logins into an existing/auto-connected account alike (see
    SOCIALACCOUNT_EMAIL_AUTHENTICATION) — so rejecting here closes the gap on
    every Google path.
    """

    def pre_social_login(self, request, sociallogin):
        email = (
            sociallogin.user.email or sociallogin.account.extra_data.get("email") or ""
        )
        if not is_signin_domain_allowed(email):
            messages.error(request, "That email domain is not allowed to sign in.")
            raise ImmediateHttpResponse(redirect("account_login"))
