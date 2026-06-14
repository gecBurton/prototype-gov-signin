import json
from functools import cached_property

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView
from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import get_application_model
from oauth2_provider.views import application as base_views
from oauth2_provider.views import base as oidc_base_views
from oauth2_provider.views import oidc as oidc_views

from users.forms import ApplicationForm
from users.models import SignInEvent

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
        # Soft-deleted (hidden) applications are excluded everywhere this is
        # used: detail, update, delete and secret regeneration.
        return get_application_model().objects.filter(team=self.team, is_active=True)

    def get_context_data(self, **kwargs):
        return super().get_context_data(team=self.team, **kwargs)


class ApplicationFormMixin(TeamApplicationMixin):
    def get_form_class(self):
        return ApplicationForm

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

    def form_valid(self, form):
        # Soft delete: hide the application rather than removing the row, so its
        # credentials and sign-in history are preserved and the action can be
        # undone (by an admin). get_queryset already excludes hidden apps.
        self.object.is_active = False
        self.object.save(update_fields=["is_active"])
        return redirect(self.get_success_url())


class TeamList(LoginRequiredMixin, ListView):
    template_name = "oauth2_provider/team_list.html"
    context_object_name = "teams"

    def get_queryset(self):
        return self.request.user.teams.all()


class PaginationMixin:
    """Add GOV.UK-style page numbers to a paginated ListView.

    Exposes ``page_range`` (page numbers with Paginator.ELLIPSIS standing in for
    gaps — the GOV.UK pattern: first, …, neighbours, …, last) and
    ``page_ellipsis`` so the shared pagination partial can render the gaps.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if context.get("is_paginated"):
            page_obj = context["page_obj"]
            context["page_range"] = page_obj.paginator.get_elided_page_range(
                page_obj.number, on_each_side=1, on_ends=1
            )
            context["page_ellipsis"] = Paginator.ELLIPSIS
        return context


class ApplicationDirectory(PaginationMixin, LoginRequiredMixin, ListView):
    """A directory of every listed application, for any signed-in user.

    Every listed application is shown (a catalogue of what exists), each tagged
    with whether the viewer can actually sign in to it — using the same domain
    check the authorize endpoint enforces (_is_domain_allowed), so the tag never
    disagrees with what happens on click. Soft-deleted (is_active=False) and
    opted-out (listed=False) applications are excluded entirely.
    """

    template_name = "oauth2_provider/application_directory.html"
    context_object_name = "applications"
    paginate_by = 20

    def get_queryset(self):
        return (
            get_application_model()
            .objects.filter(is_active=True, listed=True)
            .select_related("team")
            .prefetch_related("team__allowed_email_domains")
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        email = self.request.user.email
        # Tag each app on this page with the viewer's access. Pagination has
        # already sliced the queryset to one page, so this badges (and the
        # prefetch loads) only the apps actually shown — no per-app queries.
        for application in context["applications"]:
            application.user_has_access = _is_domain_allowed(application, email)
        return context


class SignInLog(PaginationMixin, LoginRequiredMixin, ListView):
    """Sign-in history for the applications the viewer manages.

    A user manages an application by being a member of its owning team (the same
    membership that gates the team admin pages), so this shows every SignInEvent
    for an application whose team the viewer belongs to — most recent first,
    paginated. Soft-deleted applications keep their history and still appear.
    """

    template_name = "oauth2_provider/sign_in_log.html"
    context_object_name = "events"
    paginate_by = 20

    def get_queryset(self):
        # SignInEvent.Meta already orders by -created (most recent first).
        return SignInEvent.objects.filter(
            application__team__in=self.request.user.teams.all()
        ).select_related("user", "application", "application__team")


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
            {"team": self.team, "domain_error": error, "domain_value": domain},
        )


class TeamDomainRemove(TeamMixin, View):
    def post(self, request, *args, **kwargs):
        get_object_or_404(
            self.team.allowed_email_domains, pk=kwargs["domain_pk"]
        ).delete()
        return redirect("oauth2_provider:team", pk=self.team.pk)


def _is_domain_allowed(application, email):
    # Individually allow-listed addresses (VIPs, pentesters) bypass the team's
    # domain restriction.
    if email.lower() in application.additional_email_list:
        return True
    # No domains means no one is admitted by domain (fail closed): a domain must
    # be added explicitly, so leaving the list empty never opens access to all.
    labels = email.rsplit("@", 1)[-1].lower().split(".")
    suffixes = {".".join(labels[i:]) for i in range(len(labels))}
    # Evaluate the team's domains in Python (over .all()) rather than with a
    # filtered query, so a caller that prefetches allowed_email_domains (the
    # Applications directory, rendering many apps) adds no per-app queries; the
    # authorize path, with no prefetch, issues a single .all() instead. Behaviour
    # is identical: a suffix of the user's domain must exactly match an allowed
    # domain (matching on label boundaries, so evilcabinetoffice.gov.uk does not
    # match cabinetoffice.gov.uk).
    return any(
        domain.domain in suffixes
        for domain in application.team.allowed_email_domains.all()
    )


def _reject_weak_pkce(params):
    """Return a 400 if PKCE is used with anything other than S256, else None.

    The toolkit accepts the ``plain`` challenge method, which offers no
    protection against authorization-code interception (the challenge equals
    the verifier). Require S256 whenever a challenge is present so the only
    PKCE method we accept matches what the discovery document advertises.
    """
    challenge = params.get("code_challenge")
    method = params.get("code_challenge_method")
    if challenge and method != "S256":
        return HttpResponseBadRequest(
            "Unsupported code_challenge_method; only S256 is allowed."
        )
    return None


class AuthorizationView(oidc_base_views.AuthorizationView):
    def _check_domain(self, request, client_id):
        """Return a 403 response if the user's email domain is not whitelisted, else None.

        Raises Http404 if the application has been soft-deleted (hidden), so a
        removed client can never sign anyone in.
        """
        try:
            application = get_application_model().objects.get(client_id=client_id)
        except get_application_model().DoesNotExist:
            return None  # let the parent handle the invalid client_id
        if not application.is_active:
            raise Http404("Unknown client")
        if not _is_domain_allowed(application, request.user.email):
            return render(
                request,
                "oauth2_provider/authorization_denied.html",
                {"application": application},
                status=403,
            )
        return None

    def get(self, request, *args, **kwargs):
        if weak := _reject_weak_pkce(request.GET):
            return weak
        if request.user.is_authenticated:
            client_id = request.GET.get("client_id", "")
            if denied := self._check_domain(request, client_id):
                return denied
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if weak := _reject_weak_pkce(self.request.POST):
            return weak
        client_id = form.cleaned_data["client_id"]
        if denied := self._check_domain(self.request, client_id):
            return denied
        return super().form_valid(form)

    def create_authorization_response(self, request, scopes, credentials, allow):
        # Both the consent (form_valid) and auto-approve (skip_authorization)
        # paths funnel through here, so this is the single point where a sign-in
        # is recorded. super() raises on failure, so we only log a granted code.
        response = super().create_authorization_response(
            request, scopes, credentials, allow
        )
        if allow:
            application = get_application_model().objects.get(
                client_id=credentials["client_id"]
            )
            SignInEvent.objects.create(user=request.user, application=application)
        return response


class DiscoveryInfoView(oidc_views.ConnectDiscoveryInfoView):
    """Advertise only what this server actually honours.

    The toolkit hardcodes ``HS256`` and the ``plain`` PKCE method into the
    discovery document, but every Application is constrained to RS256 (a model
    CheckConstraint) and only S256 PKCE is accepted (see _reject_weak_pkce).
    Trim those two fields so a relying party cannot be led to negotiate an
    algorithm or challenge method the server will reject. (response_types is
    narrowed to ["code"] via OIDC_RESPONSE_TYPES_SUPPORTED.)
    """

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        data = json.loads(response.content)
        data["id_token_signing_alg_values_supported"] = ["RS256"]
        data["code_challenge_methods_supported"] = ["S256"]
        response.content = json.dumps(data)
        return response
