import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.forms import ApplicationForm
from users.models import Team

User = get_user_model()
Application = get_application_model()

URL = "/o/applications/"


@pytest.fixture
def directory_team(db):
    return Team.objects.create(name="Directory Team")


def _make_app(team, **kwargs):
    defaults = {
        "name": "Catalogue App",
        "client_type": Application.CLIENT_CONFIDENTIAL,
        "redirect_uris": "http://localhost/callback",
        "team": team,
    }
    defaults.update(kwargs)
    return Application.objects.create(**defaults)


def _signed_in(client, email="viewer@example.com"):
    client.force_login(User.objects.create_user(email=email))


def test_directory_requires_login(client, db):
    response = client.get(URL)
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.parametrize(
    "is_active,listed,visible",
    [
        (True, True, True),  # active + listed: shown
        (True, False, False),  # opted out: hidden
        (False, True, False),  # soft-deleted: hidden even though listed
        (False, False, False),
    ],
)
def test_directory_visibility(client, directory_team, is_active, listed, visible):
    _make_app(directory_team, name="Visibility App", is_active=is_active, listed=listed)
    _signed_in(client)

    response = client.get(URL)

    assert response.status_code == 200
    assert (b"Visibility App" in response.content) == visible


def test_directory_shows_name_description_team_and_link(client, directory_team):
    _make_app(
        directory_team,
        name="Grafana",
        description="Dashboards and metrics",
        main_app_url="https://grafana.example.gov.uk",
    )
    _signed_in(client)

    content = client.get(URL).content.decode()

    assert "Grafana" in content
    assert "Dashboards and metrics" in content
    assert "https://grafana.example.gov.uk" in content
    assert "Directory Team" in content  # owning team is shown


def test_directory_is_global_not_scoped_to_the_users_teams(client, directory_team):
    # The directory is a catalogue of what exists: a user sees listed apps even
    # from teams they do not belong to.
    _make_app(directory_team, name="Someone Elses App")
    _signed_in(client, email="outsider@example.com")

    assert b"Someone Elses App" in client.get(URL).content


def test_listed_is_an_editable_opt_out_on_the_application_form():
    # Teams must be able to opt out via the management form, defaulting to listed.
    field = ApplicationForm().fields["listed"]
    assert field.initial is True
