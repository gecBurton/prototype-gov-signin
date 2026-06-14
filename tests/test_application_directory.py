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


# Access is badged, not filtered: every listed app is shown, tagged with whether
# the viewer can sign in (same predicate the authorize endpoint enforces).


def test_badge_shows_access_for_a_user_on_an_allowed_domain(client, directory_team):
    directory_team.allowed_email_domains.create(domain="example.com")
    _make_app(directory_team, name="Insider App")
    _signed_in(client, email="insider@example.com")

    content = client.get(URL).content.decode()

    assert "Insider App" in content
    assert "govuk-tag--green" in content
    assert "govuk-tag--grey" not in content


def test_badge_shows_no_access_for_an_ineligible_user_but_still_lists_the_app(
    client, directory_team
):
    directory_team.allowed_email_domains.create(domain="example.com")
    _make_app(directory_team, name="Restricted App")
    _signed_in(client, email="outsider@other.org")

    content = client.get(URL).content.decode()

    assert "Restricted App" in content  # shown, not hidden
    assert "govuk-tag--grey" in content
    assert "govuk-tag--green" not in content


def test_badge_shows_access_via_additional_emails(client, directory_team):
    # The team allows no domains, but the app individually allow-lists the user.
    _make_app(directory_team, name="VIP App", additional_emails="vip@other.org")
    _signed_in(client, email="vip@other.org")

    content = client.get(URL).content.decode()

    assert "govuk-tag--green" in content


def test_directory_issues_no_per_app_queries_for_access(
    client, directory_team, django_assert_max_num_queries
):
    # The prefetch must keep the access check from doing a query per application.
    directory_team.allowed_email_domains.create(domain="example.com")
    for n in range(5):
        _make_app(directory_team, name=f"App {n}")
    _signed_in(client, email="insider@example.com")

    # A fixed budget regardless of app count: session/auth + app list + team +
    # prefetched domains. Five apps must not cost five extra domain queries.
    with django_assert_max_num_queries(10):
        client.get(URL)
