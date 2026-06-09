from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms.models import modelform_factory
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
        return get_application_model().objects.filter(owners=self.request.user)


class ApplicationRegistration(base_views.ApplicationRegistration):
    def get_form_class(self):
        return modelform_factory(
            get_application_model(), fields=_APPLICATION_FORM_FIELDS
        )

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.owners.add(self.request.user)
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
            if self.object.owners.filter(pk=user.pk).exists():
                error = f"{email} is already an owner."
            else:
                self.object.owners.add(user)
                return redirect("oauth2_provider:owners", pk=self.object.pk)

        return self.render_to_response(self.get_context_data(error=error))


class ApplicationOwnerRemove(ApplicationOwnerMixin, SingleObjectMixin, View):
    def post(self, request, *args, **kwargs):
        application = self.get_object()
        user_to_remove = get_object_or_404(get_user_model(), pk=kwargs["user_pk"])

        if application.owners.count() <= 1:
            return redirect("oauth2_provider:owners", pk=application.pk)

        application.owners.remove(user_to_remove)
        return redirect("oauth2_provider:owners", pk=application.pk)


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
