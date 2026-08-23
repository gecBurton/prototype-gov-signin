"""RP-initiated logout.

The logout-challenge view shows a confirmation page and defers to Hydra's
own logout accept/reject admin API — this app makes no decision here beyond
"did the user click continue".

PKCE strictness and discovery-document trimming used to be enforced by this
app (see git history for the removed _reject_weak_pkce/DiscoveryInfoView),
but both are now Hydra's own job: OAUTH2_PKCE_ENFORCED=true (docker-compose.yml)
makes Hydra itself reject a missing or `plain` code_challenge at token
exchange, and nothing in this deployment consumes the discovery document (see
docker-compose.yml's Grafana config, which is wired with explicit endpoint
URLs), so trimming it had no remaining security value.
"""


def test_logout_endpoint_shows_confirmation(client, db):
    response = client.get("/o/logout/?logout_challenge=some-challenge")
    assert response.status_code == 200
    assert b"Sign out" in response.content


def test_logout_missing_challenge_is_bad_request(client, db):
    assert client.get("/o/logout/").status_code == 400


def test_logout_confirmation_carries_challenge_as_hidden_field(client, db):
    """The challenge is echoed into the form, not stashed in the session —
    see HydraLogoutView for why (avoids a second tab clobbering the first)."""
    response = client.get("/o/logout/?logout_challenge=some-challenge")
    assert b'name="logout_challenge" value="some-challenge"' in response.content


def test_two_concurrent_logout_confirmations_do_not_clobber_each_other(
    client, fake_hydra
):
    """Regression test: opening the logout confirmation twice (two tabs, or
    navigate-away-and-back) must not make the first tab's POST use the
    second tab's challenge — each POST carries its own challenge in the form.
    """
    client.get("/o/logout/?logout_challenge=first-challenge")
    client.get("/o/logout/?logout_challenge=second-challenge")

    response = client.post(
        "/o/logout/", {"logout_challenge": "first-challenge", "allow": "Sign out"}
    )

    assert response.status_code == 302
    assert fake_hydra.accepted_logout_challenges == ["first-challenge"]
