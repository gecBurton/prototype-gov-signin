from datetime import datetime, timezone

import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.models import SignInEvent

User = get_user_model()
Application = get_application_model()

LOGS_URL = "/o/logs/"


def _event(user, application, created=None):
    """Create a SignInEvent, overriding the auto_now_add ``created`` if given."""
    event = SignInEvent.objects.create(user=user, application=application)
    if created is not None:
        SignInEvent.objects.filter(pk=event.pk).update(created=created)
        event.refresh_from_db()
    return event


def test_logs_requires_login(client, db):
    response = client.get(LOGS_URL)
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_logs_show_managed_team_events(client, owner, app, other_team_app, stranger):
    managed = _event(stranger, app)  # someone using an app the owner manages
    # Another team's app, and not the owner's own sign-in: out of scope.
    _event(stranger, other_team_app)
    client.force_login(owner)

    response = client.get(LOGS_URL)
    assert response.status_code == 200
    assert [e.pk for e in response.context["events"]] == [managed.pk]


def test_logs_include_own_login_activity(client, stranger, other_team_app):
    # stranger manages no teams, but their own sign-ins should still show.
    own = _event(stranger, other_team_app)
    someone_else = User.objects.create_user(email="someone@example.com")
    _event(someone_else, other_team_app)  # not the viewer, not a managed app
    client.force_login(stranger)

    response = client.get(LOGS_URL)
    assert [e.pk for e in response.context["events"]] == [own.pk]


def test_application_dropdown_includes_apps_you_signed_into(
    client, stranger, other_team_app
):
    _event(stranger, other_team_app)
    client.force_login(stranger)

    response = client.get(LOGS_URL)
    assert other_team_app in list(response.context["applications"])


def test_logs_most_recent_first(client, owner, app, stranger):
    older = _event(stranger, app, created=datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer = _event(stranger, app, created=datetime(2026, 2, 1, tzinfo=timezone.utc))
    client.force_login(owner)

    response = client.get(LOGS_URL)
    assert [e.pk for e in response.context["events"]] == [newer.pk, older.pk]


def test_logs_paginated(client, owner, app, stranger):
    for _ in range(21):  # paginate_by = 20
        _event(stranger, app)
    client.force_login(owner)

    first = client.get(LOGS_URL)
    assert first.context["is_paginated"] is True
    assert len(first.context["events"]) == 20
    assert first.context["page_obj"].has_next()

    second = client.get(LOGS_URL, {"page": 2})
    assert len(second.context["events"]) == 1


def test_logs_empty_state(client, owner):
    client.force_login(owner)
    response = client.get(LOGS_URL)
    assert response.status_code == 200
    assert b"no sign-ins to show" in response.content


@pytest.fixture
def second_app(team):
    return Application.objects.create(
        name="Second App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        redirect_uris="http://localhost/callback",
        team=team,
    )


def test_filter_by_application(client, owner, app, second_app, stranger):
    wanted = _event(stranger, app)
    _event(stranger, second_app)
    client.force_login(owner)

    response = client.get(LOGS_URL, {"application": str(app.pk)})
    assert [e.pk for e in response.context["events"]] == [wanted.pk]


@pytest.mark.parametrize(
    "query",
    [
        "alice",  # local part
        "alice.smith@dsit.gov.uk",  # the whole address
        "dsit.gov.uk",  # just the domain
        "DSIT.GOV.UK",  # case-insensitive
        "smith",  # a fragment in the middle
    ],
)
def test_filter_by_user_email_is_a_partial_match(client, owner, app, query):
    alice = User.objects.create_user(email="alice.smith@dsit.gov.uk")
    bob = User.objects.create_user(email="bob@example.com")
    wanted = _event(alice, app)
    _event(bob, app)
    client.force_login(owner)

    response = client.get(LOGS_URL, {"user": query})
    assert [e.pk for e in response.context["events"]] == [wanted.pk]


def test_filter_by_date(client, owner, app, stranger):
    _event(stranger, app, created=datetime(2026, 2, 14, 23, 0, tzinfo=timezone.utc))
    wanted = _event(
        stranger, app, created=datetime(2026, 2, 15, 9, 0, tzinfo=timezone.utc)
    )
    _event(stranger, app, created=datetime(2026, 2, 16, 1, 0, tzinfo=timezone.utc))
    client.force_login(owner)

    response = client.get(
        LOGS_URL,
        {"date_day": "15", "date_month": "2", "date_year": "2026"},
    )
    assert [e.pk for e in response.context["events"]] == [wanted.pk]


@pytest.mark.parametrize("bad_application", ["not-a-uuid", "12345"])
def test_malformed_application_filter_is_ignored(
    client, owner, app, stranger, bad_application
):
    event = _event(stranger, app)
    client.force_login(owner)

    response = client.get(LOGS_URL, {"application": bad_application})
    assert response.status_code == 200
    assert [e.pk for e in response.context["events"]] == [event.pk]


@pytest.mark.parametrize(
    "date_params",
    [
        pytest.param(
            {"date_day": "32", "date_month": "2", "date_year": "2026"},
            id="impossible-day",
        ),
        pytest.param(
            {"date_day": "15", "date_month": "13", "date_year": "2026"},
            id="impossible-month",
        ),
        pytest.param(
            {"date_day": "x", "date_month": "2", "date_year": "2026"},
            id="non-numeric",
        ),
        pytest.param({"date_day": "15"}, id="partial-day-only"),
    ],
)
def test_malformed_or_partial_date_filter_is_ignored(
    client, owner, app, stranger, date_params
):
    # A half-typed or impossible date must not 500; it just doesn't constrain
    # the results (see _parse_date_parts).
    event = _event(stranger, app)
    client.force_login(owner)

    response = client.get(LOGS_URL, date_params)
    assert response.status_code == 200
    assert [e.pk for e in response.context["events"]] == [event.pk]


def test_filters_combine(client, owner, app, second_app, stranger):
    # Each filter is tested in isolation elsewhere; this locks in that they AND
    # together — only the event matching application AND user AND date survives.
    on_date = datetime(2026, 2, 15, 9, 0, tzinfo=timezone.utc)
    alice = User.objects.create_user(email="alice@example.com")
    wanted = _event(alice, app, created=on_date)
    _event(alice, app, created=datetime(2026, 2, 16, tzinfo=timezone.utc))  # wrong date
    _event(alice, second_app, created=on_date)  # wrong application
    _event(stranger, app, created=on_date)  # wrong user
    client.force_login(owner)

    response = client.get(
        LOGS_URL,
        {
            "application": str(app.pk),
            "user": "alice",
            "date_day": "15",
            "date_month": "2",
            "date_year": "2026",
        },
    )
    assert [e.pk for e in response.context["events"]] == [wanted.pk]


def test_pagination_preserves_filters(client, owner, app, stranger):
    for _ in range(21):
        _event(stranger, app)
    client.force_login(owner)

    response = client.get(LOGS_URL, {"application": str(app.pk)})
    # The filter rides along in the pagination links, not just ?page=N.
    assert f"application={app.pk}" in response.context["filter_query"]
    assert f"page=2&amp;application={app.pk}" in response.content.decode()


def test_filtered_empty_state(client, owner, app, stranger):
    _event(stranger, app)
    client.force_login(owner)

    response = client.get(LOGS_URL, {"user": "nobody@example.com"})
    assert b"No sign-ins match your filters" in response.content
