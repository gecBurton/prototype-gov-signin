"""Scaling behaviour of users.hydra's list functions.

list_team_applications uses Hydra's server-side owner filter, so it scales
with a team's own client count, not the total. list_all_active_applications
has no such filter available (it genuinely needs every application), so its
result is cached briefly to avoid a full Hydra scan on every sign-in.
"""

from users import hydra


def test_list_team_applications_ignores_other_teams_applications(
    fake_hydra, make_team, make_application
):
    team = make_team("T")
    make_application(team, name="App")
    other_team = make_team("Other")
    for n in range(20):
        make_application(other_team, name=f"Noise {n}")

    apps = hydra.list_team_applications(team.pk, include_inactive=True)

    assert [a.name for a in apps] == ["App"]


def test_list_all_active_applications_is_cached(
    fake_hydra, make_team, make_application
):
    team = make_team("T")
    make_application(team, name="App")

    first = hydra.list_all_active_applications()
    # Create a second application directly against the fake, bypassing
    # create_application (and its cache invalidation), to prove the second
    # call is served from cache rather than re-fetching from Hydra.
    fake_hydra.create_client(
        {
            "client_name": "Uncached App",
            "owner": str(team.pk),
            "metadata": {"is_active": True, "listed": True},
        }
    )
    second = hydra.list_all_active_applications()

    assert [a.name for a in first] == [a.name for a in second] == ["App"]


def test_create_application_invalidates_the_cache(
    fake_hydra, make_team, make_application
):
    team = make_team("T")
    make_application(team, name="First")
    hydra.list_all_active_applications()  # populate the cache

    make_application(team, name="Second")

    names = {a.name for a in hydra.list_all_active_applications()}
    assert names == {"First", "Second"}


def test_update_application_invalidates_the_cache(
    fake_hydra, make_team, make_application
):
    team = make_team("T")
    app = make_application(team, name="Original Name")
    hydra.list_all_active_applications()  # populate the cache

    hydra.update_application(app.client_id, name="Renamed")

    names = {a.name for a in hydra.list_all_active_applications()}
    assert names == {"Renamed"}


def test_soft_delete_invalidates_the_cache(fake_hydra, make_team, make_application):
    team = make_team("T")
    app = make_application(team, name="App")
    hydra.list_all_active_applications()  # populate the cache

    hydra.soft_delete(app.client_id)

    assert hydra.list_all_active_applications() == []


def test_list_clients_stops_on_an_empty_page_even_with_a_next_link(
    fake_hydra, requests_mock
):
    """Regression test: confirmed directly against a live Hydra instance
    that it can return rel="next" on an already-empty page (e.g. for a
    filter matching zero clients) — trusting that header alone would loop
    forever. _list_clients must stop as soon as a page has no items.
    """
    requests_mock.get(
        "http://hydra-admin.test/admin/clients",
        json=[],
        headers={
            "Link": '<http://hydra-admin.test/admin/clients?page_token=next>; rel="next"'
        },
    )

    clients = hydra._list_clients(owner="nonexistent-team")

    assert clients == []
