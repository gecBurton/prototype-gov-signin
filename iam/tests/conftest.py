import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model

Application = get_application_model()

CLIENT_ID = "demo-client-id"
CLIENT_SECRET = "demo-client-secret"
REDIRECT_URI = "http://localhost/callback"


@pytest.fixture(autouse=True, scope="session")
def configure_settings():
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.ALLOWED_HOSTS = ["testserver", "localhost"]
    if not settings.OAUTH2_PROVIDER.get("OIDC_RSA_PRIVATE_KEY"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        settings.OAUTH2_PROVIDER["OIDC_RSA_PRIVATE_KEY"] = pem


@pytest.fixture(scope="session")
def demo_user(django_db_setup, django_db_blocker):

    User = get_user_model()
    with django_db_blocker.unblock():
        user, _ = User.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@example.com"},
        )
        user.set_unusable_password()
        user.save()
    return user


@pytest.fixture(scope="session")
def oauth_app(django_db_setup, django_db_blocker):

    with django_db_blocker.unblock():
        app, _ = Application.objects.update_or_create(
            client_id=CLIENT_ID,
            defaults={
                "name": "Test Client",
                "client_type": Application.CLIENT_CONFIDENTIAL,
                "authorization_grant_type": Application.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": REDIRECT_URI,
                "client_secret": CLIENT_SECRET,
                "algorithm": "RS256",
                "skip_authorization": False,
            },
        )
    return app
