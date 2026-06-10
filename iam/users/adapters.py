from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.utils import user_email, user_username


class AccountAdapter(DefaultAccountAdapter):
    def populate_username(self, request, user):
        email = user_email(user)
        if email:
            user_username(user, email[:150])
        else:
            super().populate_username(request, user)
