from allauth.account.models import EmailAddress
from oauth2_provider.oauth2_validators import OAuth2Validator


class OIDCValidator(OAuth2Validator):
    def get_additional_claims(self, request):
        user = request.user
        # Report the real verification state rather than asserting True: a
        # relying party trusts this claim to decide whether the address is the
        # user's. Login-by-code and Google both leave a verified EmailAddress,
        # so this is True in practice for every supported flow; deriving it
        # (instead of hardcoding) means a future unverified-login path can never
        # silently mint a "verified" identity.
        email_verified = EmailAddress.objects.filter(
            user=user, email__iexact=user.email, verified=True
        ).exists()
        return {
            "email": user.email,
            "email_verified": email_verified,
            "name": user.get_full_name() or user.email,
            "preferred_username": user.email,
        }
