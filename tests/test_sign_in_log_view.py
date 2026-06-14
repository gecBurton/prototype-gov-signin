from datetime import datetime, timezone

import pytest
from django.contrib.auth import get_user_model
from oauth2_provider.models import get_application_model
from users.models import SignInEvent, Team

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


@pytest.fixture
def other_team_app(db):
    other = Team.objects.create(name="Other Team")
    return Application.objects.create(
        name="Other App",
        client_type=Application.CLIENT_CONFIDENTIAL,
        redirect_uris="http://localhost/callback",
        team=other,
    )


def test_logs_requires_login(client, db):
    response = client.get(LOGS_URL)
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_logs_show_only_managed_team_events(client, owner, app, other_team_app):
    mine = _event(owner, app)
    _event(owner, other_team_app)  # a team the viewer does not belong to
    client.force_login(owner)

    response = client.get(LOGS_URL)
    assert response.status_code == 200
    assert [e.pk for e in response.context["events"]] == [mine.pk]


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


def test_filter_by_user_email(client, owner, app):
    alice = User.objects.create_user(email="alice@example.com")
    bob = User.objects.create_user(email="bob@example.com")
    wanted = _event(alice, app)
    _event(bob, app)
    client.force_login(owner)

    response = client.get(LOGS_URL, {"user": "alice"})
    assert [e.pk for e in response.context["events"]] == [wanted.pk]


def test_filter_by_date_range(client, owner, app, stranger):
    _event(stranger, app, created=datetime(2026, 1, 10, tzinfo=timezone.utc))
    inside = _event(stranger, app, created=datetime(2026, 2, 15, tzinfo=timezone.utc))
    _event(stranger, app, created=datetime(2026, 3, 20, tzinfo=timezone.utc))
    client.force_login(owner)

    response = client.get(
        LOGS_URL,
        {
            "from_day": "1", "from_month": "2", "from_year": "2026",
            "to_day": "28", "to_month": "2", "to_year": "2026",
        },
    )
    assert [e.pk for e in response.context["events"]] == [inside.pk]


@pytest.mark.parametrize("bad_application", ["not-a-uuid", "12345"])
def test_malformed_application_filter_is_ignored(client, owner, app, stranger, bad_application):
    event = _event(stranger, app)
    client.force_login(owner)

    response = client.get(LOGS_URL, {"application": bad_application})
    assert response.status_code == 200
    assert [e.pk for e in response.context["events"]] == [event.pk]


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
