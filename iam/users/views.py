from functools import cached_property

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms.models import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView
from oauth2_provider.models import get_application_model
from oauth2_provider.views import application as base_views
from oauth2_provider.views import base as oidc_base_views

_APPLICATION_FORM_FIELDS = (
    "name",
    "client_id",
    "client_secret",
    "hash_client_secret",
    "client_type",
    "authorization_grant_type",
    "redirect_uris",
    "post_logout_redirect_uris",
    "allowed_origins",
    "algorithm",
)


class TeamApplicationMixin(LoginRequiredMixin):
    """Scope application views to the team in the URL, 404ing for non-members."""

    @cached_property
    def team(self):
        return get_object_or_404(self.request.user.teams, pk=self.kwargs["team_pk"])

    def get_queryset(self):
        return get_application_model().objects.filter(team=self.team)

    def get_context_data(self, **kwargs):
        return super().get_context_data(team=self.team, **kwargs)


class ApplicationRegistration(TeamApplicationMixin, base_views.ApplicationRegistration):
    def get_form_class(self):
        return modelform_factory(
            get_application_model(), fields=_APPLICATION_FORM_FIELDS
        )

    def form_valid(self, form):
        form.instance.team = self.team
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "oauth2_provider:detail",
            kwargs={"team_pk": self.team.pk, "pk": self.object.pk},
        )


class ApplicationDetail(TeamApplicationMixin, base_views.ApplicationDetail):
    pass


class ApplicationUpdate(TeamApplicationMixin, base_views.ApplicationUpdate):
    def get_form_class(self):
        return modelform_factory(
            get_application_model(), fields=_APPLICATION_FORM_FIELDS
        )

    def get_success_url(self):
        return reverse(
            "oauth2_provider:detail",
            kwargs={"team_pk": self.team.pk, "pk": self.object.pk},
        )


class ApplicationDelete(TeamApplicationMixin, base_views.ApplicationDelete):
    def get_success_url(self):
        return reverse("oauth2_provider:team", kwargs={"pk": self.team.pk})


class TeamList(LoginRequiredMixin, ListView):
    template_name = "oauth2_provider/team_list.html"
    context_object_name = "teams"

    def get_queryset(self):
        return self.request.user.teams.all()


class TeamDetail(LoginRequiredMixin, View):
    template_name = "oauth2_provider/team_detail.html"

    def _get_team(self, request):
        return get_object_or_404(request.user.teams, pk=self.kwargs["pk"])

    def _render(self, request, team, error=None):
        return render(request, self.template_name, {"team": team, "error": error})

    def get(self, request, *args, **kwargs):
        return self._render(request, self._get_team(request))

    def post(self, request, *args, **kwargs):
        team = self._get_team(request)
        email = request.POST.get("email", "").strip()
        User = get_user_model()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return self._render(
                request, team, error=f"No user found with email {email}."
            )
        if user.teams.filter(pk=team.pk).exists():
            return self._render(
                request, team, error=f"{email} is already a team member."
            )
        user.teams.add(team)
        return redirect("oauth2_provider:team", pk=team.pk)


class TeamMemberRemove(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        team = get_object_or_404(request.user.teams, pk=kwargs["pk"])
        user_to_remove = get_object_or_404(get_user_model(), pk=kwargs["user_pk"])
        user_to_remove.teams.remove(team)
        return redirect("oauth2_provider:team", pk=team.pk)


class TeamDomainAdd(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        team = get_object_or_404(request.user.teams, pk=kwargs["pk"])
        domain = request.POST.get("domain", "").strip().lower()
        if not domain:
            error = "Enter a domain."
        elif "." not in domain:
            error = f"{domain} is too broad. Enter a full domain, like cabinetoffice.gov.uk."
        elif team.allowed_email_domains.filter(domain=domain).exists():
            error = f"{domain} is already allowed."
        else:
            team.allowed_email_domains.create(domain=domain)
            return redirect("oauth2_provider:team", pk=team.pk)
        return render(
            request,
            "oauth2_provider/team_detail.html",
            {"team": team, "domain_error": error},
        )


class TeamDomainRemove(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        team = get_object_or_404(request.user.teams, pk=kwargs["pk"])
        get_object_or_404(team.allowed_email_domains, pk=kwargs["domain_pk"]).delete()
        return redirect("oauth2_provider:team", pk=team.pk)


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
