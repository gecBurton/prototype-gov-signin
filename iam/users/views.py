from functools import cached_property

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms.models import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView
from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import get_application_model
from oauth2_provider.views import application as base_views
from oauth2_provider.views import base as oidc_base_views

_APPLICATION_FORM_FIELDS = (
    "name",
    "client_type",
    "redirect_uris",
    "post_logout_redirect_uris",
    "allowed_origins",
)

# Credentials are issued by the server, never chosen by the user. The raw
# secret is stashed in the session so the detail page can show it exactly once.
_RAW_SECRET_SESSION_KEY = "application_raw_client_secret"


class TeamMixin(LoginRequiredMixin):
    """Resolve the team from the URL, 404ing for non-members."""

    team_url_kwarg = "pk"

    @cached_property
    def team(self):
        return get_object_or_404(
            self.request.user.teams, pk=self.kwargs[self.team_url_kwarg]
        )


class TeamApplicationMixin(TeamMixin):
    """Scope application views to the team in the URL."""

    team_url_kwarg = "team_pk"

    def get_queryset(self):
        return get_application_model().objects.filter(team=self.team)

    def get_context_data(self, **kwargs):
        return super().get_context_data(team=self.team, **kwargs)


class ApplicationFormMixin(TeamApplicationMixin):
    def get_form_class(self):
        return modelform_factory(
            get_application_model(), fields=_APPLICATION_FORM_FIELDS
        )

    def get_success_url(self):
        return reverse(
            "oauth2_provider:detail",
            kwargs={"team_pk": self.team.pk, "pk": self.object.pk},
        )


def _stash_raw_secret(request, application, raw_secret):
    request.session[_RAW_SECRET_SESSION_KEY] = {
        "application": str(application.pk),
        "secret": raw_secret,
    }


class ApplicationRegistration(ApplicationFormMixin, base_views.ApplicationRegistration):
    def form_valid(self, form):
        form.instance.team = self.team
        # Saving hashes the generated secret, so capture the raw value first.
        raw_secret = form.instance.client_secret
        response = super().form_valid(form)
        _stash_raw_secret(self.request, self.object, raw_secret)
        return response


class ApplicationDetail(TeamApplicationMixin, base_views.ApplicationDetail):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stashed = self.request.session.pop(_RAW_SECRET_SESSION_KEY, None)
        if stashed and stashed["application"] == str(self.object.pk):
            context["raw_client_secret"] = stashed["secret"]
        return context


class ApplicationSecretRegenerate(TeamApplicationMixin, View):
    def post(self, request, *args, **kwargs):
        application = get_object_or_404(self.get_queryset(), pk=kwargs["pk"])
        raw_secret = generate_client_secret()
        application.client_secret = raw_secret
        application.save()
        _stash_raw_secret(request, application, raw_secret)
        return redirect(
            "oauth2_provider:detail", team_pk=self.team.pk, pk=application.pk
        )


class ApplicationUpdate(ApplicationFormMixin, base_views.ApplicationUpdate):
    pass


class ApplicationDelete(TeamApplicationMixin, base_views.ApplicationDelete):
    def get_success_url(self):
        return reverse("oauth2_provider:team", kwargs={"pk": self.team.pk})


class TeamList(LoginRequiredMixin, ListView):
    template_name = "oauth2_provider/team_list.html"
    context_object_name = "teams"

    def get_queryset(self):
        return self.request.user.teams.all()


class TeamDetail(TeamMixin, View):
    template_name = "oauth2_provider/team_detail.html"

    def _render(self, request, error=None):
        return render(request, self.template_name, {"team": self.team, "error": error})

    def get(self, request, *args, **kwargs):
        return self._render(request)

    def post(self, request, *args, **kwargs):
        email = request.POST.get("email", "").strip()
        User = get_user_model()
        # One message for both failure modes, so the form does not reveal
        # which email addresses have accounts.
        error = (
            f"Could not add {email}. They need to have signed in to this "
            "service before, and must not already be a team member."
        )
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return self._render(request, error=error)
        if user.teams.filter(pk=self.team.pk).exists():
            return self._render(request, error=error)
        user.teams.add(self.team)
        return redirect("oauth2_provider:team", pk=self.team.pk)


class TeamMemberRemove(TeamMixin, View):
    def post(self, request, *args, **kwargs):
        user_to_remove = get_object_or_404(get_user_model(), pk=kwargs["user_pk"])
        # A team with no members would be unmanageable except via the admin,
        # so the last member cannot be removed.
        is_member = user_to_remove.teams.filter(pk=self.team.pk).exists()
        if is_member and not self.team.members.exclude(pk=user_to_remove.pk).exists():
            return render(
                request,
                "oauth2_provider/team_detail.html",
                {
                    "team": self.team,
                    "member_error": "You cannot remove the last member of a team.",
                },
            )
        user_to_remove.teams.remove(self.team)
        return redirect("oauth2_provider:team", pk=self.team.pk)


class TeamDomainAdd(TeamMixin, View):
    def post(self, request, *args, **kwargs):
        domain = request.POST.get("domain", "").strip().lower()
        if not domain:
            error = "Enter a domain."
        elif "." not in domain:
            error = f"{domain} is too broad. Enter a full domain, like cabinetoffice.gov.uk."
        elif self.team.allowed_email_domains.filter(domain=domain).exists():
            error = f"{domain} is already allowed."
        else:
            self.team.allowed_email_domains.create(domain=domain)
            return redirect("oauth2_provider:team", pk=self.team.pk)
        return render(
            request,
            "oauth2_provider/team_detail.html",
            {"team": self.team, "domain_error": error},
        )


class TeamDomainRemove(TeamMixin, View):
    def post(self, request, *args, **kwargs):
        get_object_or_404(
            self.team.allowed_email_domains, pk=kwargs["domain_pk"]
        ).delete()
        return redirect("oauth2_provider:team", pk=self.team.pk)


def _is_domain_allowed(application, email):
    if application.team is None:
        return True
    allowed = application.team.allowed_email_domains
    labels = email.rsplit("@", 1)[-1].lower().split(".")
    suffixes = [".".join(labels[i:]) for i in range(len(labels))]
    return allowed.filter(domain__in=suffixes).exists() or not allowed.exists()


class AuthorizationView(oidc_base_views.AuthorizationView):
    def _check_domain(self, request, client_id):
        """Return a 403 response if the user's email domain is not whitelisted, else None."""
        try:
            application = get_application_model().objects.get(client_id=client_id)
        except get_application_model().DoesNotExist:
            return None  # let the parent handle the invalid client_id
        if not _is_domain_allowed(application, request.user.email):
            return render(
                request,
                "oauth2_provider/authorization_denied.html",
                {"application": application},
                status=403,
            )
        return None

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            client_id = request.GET.get("client_id", "")
            if denied := self._check_domain(request, client_id):
                return denied
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        client_id = form.cleaned_data["client_id"]
        if denied := self._check_domain(self.request, client_id):
            return denied
        return super().form_valid(form)
