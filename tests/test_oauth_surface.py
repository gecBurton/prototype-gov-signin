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
