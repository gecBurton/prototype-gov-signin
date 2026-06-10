import pytest
from django.contrib.auth import get_user_model
from users.adapters import AccountAdapter

User = get_user_model()


@pytest.mark.parametrize(
    "user_kwargs, expected_username",
    [
        (
            {"email": "george.burton@example.com", "first_name": "George"},
            "george.burton@example.com",
        ),
        ({"first_name": "George", "last_name": "Burton"}, "george"),
    ],
)
def test_populate_username(db, user_kwargs, expected_username):
    user = User(**user_kwargs)

    AccountAdapter().populate_username(None, user)

    assert user.username == expected_username
