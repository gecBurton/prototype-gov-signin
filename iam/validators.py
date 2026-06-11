from oauth2_provider.oauth2_validators import OAuth2Validator


class OIDCValidator(OAuth2Validator):
    def get_additional_claims(self, request):
        user = request.user
        return {
            "email": user.email,
            # True for every login flow we offer: login-by-code proves control
            # of the mailbox, and Google only reports verified addresses. If a
            # flow that skips verification is ever added, derive this from
            # allauth's EmailAddress.verified instead.
            "email_verified": True,
            "name": user.get_full_name() or user.email,
            "preferred_username": user.email,
        }
