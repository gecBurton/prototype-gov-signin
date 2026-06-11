import pytest


@pytest.mark.parametrize(
    "authed_client,expected_status",
    [("owner", 200), (None, 302)],
    indirect=["authed_client"],
)
def test_profile_access(authed_client, expected_status):
    assert authed_client.get("/accounts/profile/").status_code == expected_status


def test_profile_shows_userinfo_claims(client, owner):
    client.force_login(owner)
    content = client.get("/accounts/profile/").content.decode()
    # The page shows exactly what the userinfo endpoint returns.
    assert str(owner.pk) in content
    assert owner.email in content
    for claim in ("sub", "email", "email_verified", "name", "preferred_username"):
        assert claim in content


def test_header_links_to_profile_when_signed_in(client, owner):
    client.force_login(owner)
    content = client.get("/").content.decode()
    assert 'href="/accounts/profile/"' in content
    assert owner.email in content


def test_header_has_no_profile_link_when_signed_out(client, db):
    assert 'href="/accounts/profile/"' not in client.get("/").content.decode()
