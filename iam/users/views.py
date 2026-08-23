from datetime import date
from functools import cached_property
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from users import hydra
from users.domains import email_domain_suffixes
from users.forms import ApplicationForm
from users.models import AllowedEmailDomain, SignInEvent

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
    """Scope application views to the team in the URL, resolving from Hydra."""

    team_url_kwarg = "team_pk"
    application_url_kwarg = "pk"

    @cached_property
    def application(self):
        app = hydra.get_application(self.kwargs[self.application_url_kwarg])
        # Not found, belongs to a different team, or soft-deleted: all 404,
        # matching the previous get_queryset()-based scoping.
        if app is None or app.team_id != str(self.team.pk) or not app.is_active:
            raise Http404("Unknown application")
        return app

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            team=self.team, application=self.application, **kwargs
        )


class ApplicationRegistration(TeamMixin, FormView):
    template_name = "oauth2_provider/application_registration_form.html"
    form_class = ApplicationForm
    team_url_kwarg = "team_pk"

    def get_context_data(self, **kwargs):
        return super().get_context_data(team=self.team, **kwargs)

    def form_valid(self, form):
        application = hydra.create_application(
            team_id=self.team.pk, **form.to_hydra_kwargs()
        )
        self.request.session[_RAW_SECRET_SESSION_KEY] = {
            "application": application.client_id,
            "secret": application.client_secret,
        }
        self._created = application
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "oauth2_provider:detail",
            kwargs={"team_pk": self.team.pk, "pk": self._created.client_id},
        )


class ApplicationDetail(TeamApplicationMixin, TemplateView):
    template_name = "oauth2_provider/application_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stashed = self.request.session.pop(_RAW_SECRET_SESSION_KEY, None)
        if stashed and stashed["application"] == self.application.client_id:
            context["raw_client_secret"] = stashed["secret"]
        return context


class ApplicationSecretRegenerate(TeamApplicationMixin, View):
    def post(self, request, *args, **kwargs):
        application = hydra.regenerate_secret(self.application.client_id)
        request.session[_RAW_SECRET_SESSION_KEY] = {
            "application": application.client_id,
            "secret": application.client_secret,
        }
        return redirect(
            "oauth2_provider:detail", team_pk=self.team.pk, pk=application.client_id
        )


class ApplicationUpdate(TeamApplicationMixin, FormView):
    template_name = "oauth2_provider/application_form.html"
    form_class = ApplicationForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method == "GET":
            kwargs["application"] = self.application
        return kwargs

    def form_valid(self, form):
        hydra.update_application(self.application.client_id, **form.to_hydra_kwargs())
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "oauth2_provider:detail",
            kwargs={"team_pk": self.team.pk, "pk": self.application.client_id},
        )


class ApplicationDelete(TeamApplicationMixin, View):
    def get(self, request, *args, **kwargs):
        return render(
            request,
            "oauth2_provider/application_confirm_delete.html",
            {"team": self.team, "application": self.application},
        )

    def post(self, request, *args, **kwargs):
        # Soft delete: hide the application rather than removing it from
        # Hydra, so its credentials and sign-in history are preserved and the
        # action can be undone (by an admin, via Hydra's admin API directly).
        hydra.soft_delete(self.application.client_id)
        return redirect("oauth2_provider:team", pk=self.team.pk)


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
        # Everything in the URL except the page number, so the pagination links
        # carry the current filters forward instead of resetting to page 1's
        # unfiltered view.
        query = self.request.GET.copy()
        query.pop("page", None)
        context["filter_query"] = query.urlencode()
        return context


class ApplicationDirectory(PaginationMixin, LoginRequiredMixin, TemplateView):
    """A directory of every listed application, for any signed-in user.

    Every listed application is shown (a catalogue of what exists), each tagged
    with whether the viewer can actually sign in to it — using the same domain
    check the authorize endpoint enforces (_is_domain_allowed), so the tag never
    disagrees with what happens on click. Soft-deleted (is_active=False) and
    opted-out (listed=False) applications are excluded entirely.

    Unlike the previous SQL-backed version, application data comes from
    Hydra's admin API: there is no database table to filter/annotate/paginate
    in SQL, so this fetches every listed+active application and paginates in
    Python. Fine at the scale a handful of teams' self-registered apps implies;
    would need a different approach (e.g. a local read-through cache) if the
    number of registered applications ever grew large.
    """

    template_name = "oauth2_provider/application_directory.html"
    paginate_by = 20

    def _visible_applications(self):
        apps = [app for app in hydra.list_all_active_applications() if app.listed]
        if search := self.request.GET.get("search", "").strip():
            search = search.lower()
            apps = [
                app
                for app in apps
                if search in app.name.lower() or search in app.description.lower()
            ]
        apps.sort(key=lambda a: a.name.lower())
        return apps

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        suffixes = email_domain_suffixes(self.request.user.email)
        team_domains = _teams_with_matching_domain(suffixes)
        apps = self._visible_applications()
        for app in apps:
            app.user_has_access = app.team_id in team_domains
        if self.request.GET.get("access_only"):
            apps = [app for app in apps if app.user_has_access]

        paginator = Paginator(apps, self.paginate_by)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context.update(
            applications=page_obj.object_list,
            page_obj=page_obj,
            paginator=paginator,
            is_paginated=page_obj.has_other_pages(),
            search=self.request.GET.get("search", ""),
            access_only=bool(self.request.GET.get("access_only")),
        )
        return context


def _teams_with_matching_domain(suffixes: set[str]) -> set[str]:
    """The ids (as strings) of every team with a domain in ``suffixes``."""
    return set(
        str(team_id)
        for team_id in AllowedEmailDomain.objects.filter(
            domain__in=suffixes
        ).values_list("team_id", flat=True)
    )


class SignInLog(PaginationMixin, LoginRequiredMixin, ListView):
    """Sign-in history relevant to the viewer.

    Shows two kinds of SignInEvent: those for an application the viewer manages
    (they belong to its owning team — the same membership that gates the team
    admin pages), and the viewer's own sign-ins anywhere. So a team member sees
    who is using their applications, while an end user who manages nothing still
    sees their own login activity. Most recent first, paginated; soft-deleted
    applications keep their history and still appear (the event stores its own
    application_name/team snapshot, since Hydra is not queried here).
    """

    template_name = "oauth2_provider/sign_in_log.html"
    context_object_name = "events"
    paginate_by = 20

    def _visible_q(self):
        """Events for an app the viewer manages, or the viewer's own sign-ins."""
        user = self.request.user
        return Q(team__in=user.teams.all()) | Q(user=user)

    def _filterable_applications(self):
        """Every (client_id, name) pair that can appear in the log filter."""
        events = SignInEvent.objects.filter(self._visible_q())
        seen = {}
        for client_id, name in events.values_list(
            "application_client_id", "application_name"
        ).distinct():
            seen[client_id] = name
        return sorted(seen.items(), key=lambda pair: pair[1].lower())

    def get_queryset(self):
        events = SignInEvent.objects.filter(self._visible_q()).select_related("user")
        params = self.request.GET

        application = params.get("application", "")
        if application:
            events = events.filter(application_client_id=application)
        if email := params.get("user", "").strip():
            events = events.filter(user__email__icontains=email)
        if day := _parse_date_parts(params, "date"):
            events = events.filter(created__date=day)
        return events

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["applications"] = self._filterable_applications()
        # Echo the submitted values back so the form stays populated.
        context["filters"] = self.request.GET
        context["has_filters"] = any(
            self.request.GET.get(key, "").strip()
            for key in (
                "application",
                "user",
                "date_day",
                "date_month",
                "date_year",
            )
        )
        return context


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


def _parse_date_parts(params, prefix):
    """Build a date from ``{prefix}_day/_month/_year`` GET params, or None.

    A blank or unparseable date is treated as "no bound" rather than an error,
    so a half-typed filter never 500s — it just doesn't constrain the results.
    """
    parts = [
        params.get(f"{prefix}_{unit}", "").strip() for unit in ("day", "month", "year")
    ]
    if not all(parts):
        return None
    try:
        day, month, year = (int(part) for part in parts)
        return date(year, month, day)
    except ValueError:
        return None


def _is_domain_allowed(application, email):
    """Whether ``email`` may sign in to ``application`` (a users.hydra.Application).

    Individually allow-listed addresses (VIPs, pentesters) bypass the team's
    domain restriction. No domains means no one is admitted by domain (fail
    closed): a domain must be added explicitly, so leaving the list empty
    never opens access to all.
    """
    if email.lower() in application.additional_email_list:
        return True
    suffixes = email_domain_suffixes(email)
    return AllowedEmailDomain.objects.filter(
        team_id=application.team_id, domain__in=suffixes
    ).exists()


def _reject_weak_pkce(login_request):
    """Return a 400 response if the request used weak PKCE, else None.

    Hydra accepts the ``plain`` challenge method, which offers no protection
    against authorization-code interception (the challenge equals the
    verifier). Require S256 whenever a challenge is present. The
    code_challenge/method live in the original relying-party request URL,
    echoed back on the login request Hydra hands us.
    """
    query = parse_qs(urlparse(login_request.get("request_url", "")).query)
    challenge = query.get("code_challenge", [""])[0]
    method = query.get("code_challenge_method", [""])[0]
    if challenge and method != "S256":
        return HttpResponseBadRequest(
            "Unsupported code_challenge_method; only S256 is allowed."
        )
    return None


class HydraLoginView(LoginRequiredMixin, View):
    """The Hydra login-challenge endpoint (``/urls/login`` in Hydra's config).

    By the time this view runs, the user has already authenticated to this
    service via allauth (LoginRequiredMixin sends them through the normal
    email-code/Google flow first, preserving ?login_challenge= via ?next=).
    All that is left to decide is: does this user's email domain admit the
    application making the request? If so, accept the Hydra login request
    (immediately — there is no separate "log in" step here, since allauth
    already established who the user is); if not, reject it with a 403-style
    page, mirroring the previous AuthorizationView._check_domain behaviour.
    """

    template_name = "oauth2_provider/authorization_denied.html"

    def get(self, request, *args, **kwargs):
        challenge = request.GET.get("login_challenge", "")
        if not challenge:
            return HttpResponseBadRequest("Missing login_challenge.")
        try:
            login_request = hydra.get_login_request(challenge)
        except hydra.HydraAdminError:
            raise Http404("Unknown or expired login request.")

        if weak := _reject_weak_pkce(login_request):
            return weak

        application = hydra.application_from_client(login_request["client"])
        if not application.is_active:
            raise Http404("Unknown client")

        if not _is_domain_allowed(application, request.user.email):
            return render(
                request, self.template_name, {"application": application}, status=403
            )

        redirect_to = hydra.accept_login(challenge, subject=str(request.user.pk))
        return redirect(redirect_to)


class HydraConsentView(LoginRequiredMixin, View):
    """The Hydra consent-challenge endpoint (``/urls/consent``).

    Every application this service registers is created with
    ``skip_consent`` following the application's own ``skip_authorization``
    setting, so this view's job is mostly to accept immediately and record
    the SignInEvent — but it still renders an explicit consent screen for
    applications that have not opted into skipping it, matching the previous
    AuthorizationView/authorize.html behaviour.
    """

    template_name = "oauth2_provider/authorize.html"

    def get(self, request, *args, **kwargs):
        challenge = request.GET.get("consent_challenge", "")
        if not challenge:
            return HttpResponseBadRequest("Missing consent_challenge.")
        try:
            consent_request = hydra.get_consent_request(challenge)
        except hydra.HydraAdminError:
            raise Http404("Unknown or expired consent request.")

        if consent_request.get("skip") or consent_request["client"].get("skip_consent"):
            return self._accept(request, challenge, consent_request)

        application = hydra.application_from_client(consent_request["client"])
        return render(
            request,
            self.template_name,
            {
                "application": application,
                "scopes_descriptions": consent_request.get("requested_scope", []),
                "challenge": challenge,
            },
        )

    def post(self, request, *args, **kwargs):
        challenge = request.POST.get("consent_challenge", "")
        if "allow" not in request.POST:
            return redirect(hydra.reject_consent(challenge))

        try:
            consent_request = hydra.get_consent_request(challenge)
        except hydra.HydraAdminError:
            raise Http404("Unknown or expired consent request.")
        return self._accept(request, challenge, consent_request)

    def _accept(self, request, challenge, consent_request):
        application = hydra.application_from_client(consent_request["client"])
        redirect_to = hydra.accept_consent(
            challenge,
            grant_scope=consent_request.get("requested_scope", []),
            user=request.user,
        )
        SignInEvent.objects.create(
            user=request.user,
            application_client_id=application.client_id,
            application_name=application.name,
            team_id=application.team_id or None,
        )
        return redirect(redirect_to)


class HydraLogoutView(View):
    """The Hydra RP-initiated-logout endpoint (``/urls/logout``)."""

    template_name = "oauth2_provider/logout_confirm.html"

    def get(self, request, *args, **kwargs):
        challenge = request.GET.get("logout_challenge", "")
        if not challenge:
            return HttpResponseBadRequest("Missing logout_challenge.")
        request.session["logout_challenge"] = challenge
        return render(request, self.template_name, {})

    def post(self, request, *args, **kwargs):
        challenge = request.session.pop("logout_challenge", "")
        if "allow" in request.POST:
            redirect_to = hydra.accept_logout(challenge)
        else:
            redirect_to = hydra.reject_logout(challenge)
        return redirect(redirect_to)


class DiscoveryInfoView(View):
    """Proxy Hydra's discovery document, trimmed to what this server honours.

    See users.hydra.discovery_document for what's trimmed and why.
    """

    def get(self, request, *args, **kwargs):
        return JsonResponse(hydra.discovery_document())
