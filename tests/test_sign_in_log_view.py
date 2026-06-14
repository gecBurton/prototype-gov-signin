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
