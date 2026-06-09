from oauth2_provider.oauth2_validators import OAuth2Validator


class OIDCValidator(OAuth2Validator):
    def get_additional_claims(self, request):
        user = request.user
        return {
            "email": user.email,
            "email_verified": True,
            "name": user.get_full_name() or user.username,
            "preferred_username": user.username,
        }
