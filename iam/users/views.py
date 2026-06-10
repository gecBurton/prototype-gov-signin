from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms.models import modelform_factory
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView
from django.views.generic.detail import SingleObjectMixin
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
    "allowed_email_domains",
)


class ApplicationOwnerMixin(LoginRequiredMixin):
    def get_queryset(self):
        team = self.request.user.team
        if team is None:
            return get_application_model().objects.none()
        return get_application_model().objects.filter(team=team)


class ApplicationRegistration(base_views.ApplicationRegistration):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.team is None:
            return HttpResponseForbidden(
                "You must be a member of a team to register an application."
            )
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return modelform_factory(
            get_application_model(), fields=_APPLICATION_FORM_FIELDS
        )

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.team = self.request.user.team
        self.object.save()
        return response


class ApplicationList(ApplicationOwnerMixin, base_views.ApplicationList):
    pass


class ApplicationDetail(ApplicationOwnerMixin, base_views.ApplicationDetail):
    pass


class ApplicationUpdate(ApplicationOwnerMixin, base_views.ApplicationUpdate):
    def get_form_class(self):
        return modelform_factory(
            get_application_model(), fields=_APPLICATION_FORM_FIELDS
        )


class ApplicationDelete(ApplicationOwnerMixin, base_views.ApplicationDelete):
    pass


class ApplicationOwnerManage(ApplicationOwnerMixin, DetailView):
    context_object_name = "application"
    template_name = "oauth2_provider/application_owners.html"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        email = request.POST.get("email", "").strip()
        User = get_user_model()
        error = None

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            error = f"No user found with email {email}."
        else:
            if user.team_id == self.object.team_id:
                error = f"{email} is already a team member."
            else:
                user.team = self.object.team
                user.save()
                return redirect("oauth2_provider:owners", pk=self.object.pk)

        return self.render_to_response(self.get_context_data(error=error))


class ApplicationOwnerRemove(ApplicationOwnerMixin, SingleObjectMixin, View):
    def post(self, request, *args, **kwargs):
        application = self.get_object()
        user_to_remove = get_object_or_404(get_user_model(), pk=kwargs["user_pk"])

        if user_to_remove.team_id == application.team_id:
            user_to_remove.team = None
            user_to_remove.save()

        return redirect("oauth2_provider:owners", pk=application.pk)


class TeamManage(LoginRequiredMixin, View):
    template_name = "oauth2_provider/team.html"

    def _render(self, request, error=None):
        return render(
            request, self.template_name, {"team": request.user.team, "error": error}
        )

    def get(self, request, *args, **kwargs):
        return self._render(request)

    def post(self, request, *args, **kwargs):
        if request.user.team is None:
            return HttpResponseForbidden()
        email = request.POST.get("email", "").strip()
        User = get_user_model()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return self._render(request, error=f"No user found with email {email}.")
        if user.team_id == request.user.team_id:
            return self._render(request, error=f"{email} is already a team member.")
        user.team = request.user.team
        user.save()
        return redirect("oauth2_provider:team")


class TeamMemberRemove(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        if request.user.team is None:
            return HttpResponseForbidden()
        user_to_remove = get_object_or_404(get_user_model(), pk=kwargs["user_pk"])
        if user_to_remove.team_id == request.user.team_id:
            user_to_remove.team = None
            user_to_remove.save()
        return redirect("oauth2_provider:team")


def _is_domain_allowed(application, email):
    domains = application.allowed_email_domains.strip()
    if not domains:
        return True
    user_domain = email.rsplit("@", 1)[-1].lower()
    allowed = {d.strip().lower() for d in domains.splitlines() if d.strip()}
    return user_domain in allowed


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
