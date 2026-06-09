from allauth.account.adapter import get_adapter
from allauth.account.forms import RequestLoginCodeForm
from allauth.account.models import EmailAddress
from allauth.account.utils import filter_users_by_email
from allauth.core import context, ratelimit
from django.contrib.auth import get_user_model

User = get_user_model()


class AutoEnrollRequestLoginCodeForm(RequestLoginCodeForm):
    def clean_email(self) -> str:
        email = self.cleaned_data.get("email")
        if not email:
            return email
        if not ratelimit.consume(
            context.request, action="request_login_code", key=email.lower()
        ):
            raise get_adapter().validation_error("too_many_login_attempts")
        users = filter_users_by_email(email, is_active=True, prefer_verified=True)
        if users:
            self._user = users[0]
        else:
            user = User(email=email, username=email[:150])
            user.set_unusable_password()
            user.save()
            EmailAddress.objects.create(
                user=user, email=email, primary=True, verified=True
            )
            self._user = user
        return email
