"""The "Sign in with Google" flow, driven against the local Dex stand-in.

docker compose points the allauth Google adapter's endpoint URLs at Dex
(see integration_tests/dex.yaml), so this exercises the production Google
code path end to end — only the endpoint URLs differ from production.
"""

import uuid

from conftest import IAM, create_team
from playwright.sync_api import Page, expect

# The static user configured in integration_tests/dex.yaml.
DEX_EMAIL = "dex-user@example.com"
DEX_PASSWORD = "password"


def login_via_google(page: Page) -> None:
    page.goto(f"{IAM}/accounts/login/")
    page.get_by_role("link", name="Sign in with Google").click()

    # allauth's interstitial: "You are about to sign in using a third-party
    # account from Google."
    page.get_by_role("button", name="Continue").click()

    # Dex's login form.
    page.fill('input[name="login"]', DEX_EMAIL)
    page.fill('input[name="password"]', DEX_PASSWORD)
    page.locator('button[type="submit"]').click()

    # Back at IAM, signed in.
    page.wait_for_url(f"{IAM}/")


def test_google_login_signs_in_existing_account(page: Page):
    """A Google login is linked to the existing account with the same email.

    The user is seeded directly in the database (no Google involved), so
    seeing their team after the Dex round-trip proves the social login
    authenticated the existing account rather than creating a duplicate.
    """
    team = f"e2e-dex-team-{uuid.uuid4().hex[:8]}"
    create_team(team, DEX_EMAIL)

    login_via_google(page)

    page.goto(f"{IAM}/o/teams/")
    expect(page.get_by_role("link", name=team)).to_be_visible()
