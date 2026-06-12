from django.contrib.admin import AdminSite
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.urls import reverse


class IAMAdminSite(AdminSite):
    """Admin site that authenticates via allauth instead of a password form.

    Django's built-in admin login is the only password surface in this service
    and has no brute-force protection. Route unauthenticated admin access
    through allauth's passwordless, rate-limited login (email code / Google)
    instead, so admin access becomes "signed in via allauth AND is_staff" with
    no password for an attacker to guess.
    """

    def login(self, request, extra_context=None):
        if self.has_permission(request):
            # Signed-in staff: default behaviour (redirects on to the admin).
            return super().login(request, extra_context)
        if request.user.is_authenticated:
            # Signed in but not staff: deny. Never present a password form, and
            # do not redirect back to login (which would loop).
            raise PermissionDenied
        target = request.GET.get(REDIRECT_FIELD_NAME) or reverse(
            "admin:index", current_app=self.name
        )
        return redirect_to_login(target, reverse("account_login"))
