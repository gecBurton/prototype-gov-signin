import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


@pytest.fixture
def anon_client(db):
    return Client()


def test_new_user_is_created_on_login_code_request(anon_client):
    email = "new.user@example.com"
    assert not User.objects.filter(email=email).exists()

    anon_client.post("/accounts/login/code/", {"email": email})

    assert User.objects.filter(email=email).exists()
    user = User.objects.get(email=email)
    assert not user.has_usable_password()
    assert EmailAddress.objects.filter(user=user, email=email, verified=True).exists()


def test_new_user_redirected_to_code_confirm(anon_client):
    response = anon_client.post(
        "/accounts/login/code/",
        {"email": "another.new@example.com"},
    )
    assert response.status_code == 302
    assert "/accounts/login/code/confirm/" in response["Location"]


def test_existing_user_not_duplicated(db):
    email = "existing@example.com"
    user = User.objects.create_user(username="existing", email=email)
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)

    client = Client()
    client.post("/accounts/login/code/", {"email": email})

    assert User.objects.filter(email=email).count() == 1


@pytest.mark.parametrize(
    "email",
    [
        "user1@alpha.com",
        "user2@beta.org",
    ],
)
def test_auto_enrol_works_for_various_emails(anon_client, email):
    anon_client.post("/accounts/login/code/", {"email": email})
    assert User.objects.filter(email=email).exists()


def test_auto_enrol_sends_login_code_email(anon_client, mailoutbox):
    email = "brand.new@example.com"
    anon_client.post("/accounts/login/code/", {"email": email})
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [email]


def test_auto_enrolled_user_receives_code_on_second_request(db, mailoutbox):
    email = "returning@example.com"
    Client().post("/accounts/login/code/", {"email": email})
    Client().post("/accounts/login/code/", {"email": email})
    assert User.objects.filter(email=email).count() == 1
    assert len(mailoutbox) == 2
