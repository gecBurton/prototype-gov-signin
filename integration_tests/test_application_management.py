import base64
import hashlib
import secrets
import uuid

from conftest import DEMO_EMAIL, IAM, clear_mailbox, login_to_iam
from playwright.sync_api import Page, expect


def register_application(
    page: Page, *, name: str, client_id: str, allowed_email_domains: str = ""
) -> None:
    """Fill in and submit the application registration form."""
    page.goto(f"{IAM}/o/applications/register/")
    page.fill('[name="name"]', name)
    page.fill('[name="client_id"]', client_id)
    page.fill('[name="client_secret"]', secrets.token_urlsafe(24))
    page.select_option('[name="client_type"]', "confidential")
    page.select_option('[name="authorization_grant_type"]', "authorization-code")
    page.fill('[name="redirect_uris"]', "http://localhost/callback")
    page.select_option('[name="algorithm"]', "RS256")
    if allowed_email_domains:
        page.fill('[name="allowed_email_domains"]', allowed_email_domains)
    page.get_by_role("button", name="Save").click()
    page.wait_for_url(f"{IAM}/o/applications/*/")


def _pkce_params(client_id: str) -> str:
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return (
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&scope=openid"
        f"&redirect_uri=http://localhost/callback"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )


def test_register_application(page: Page, fresh_email: str):
    login_to_iam(page, fresh_email)

    client_id = f"e2e-{uuid.uuid4().hex[:8]}"
    register_application(page, name="My E2E App", client_id=client_id)

    # Detail page should show the client ID.
    expect(page.locator("code").first).to_have_text(client_id)
    expect(page.locator("h1")).to_contain_text("My E2E App")


def test_add_and_remove_owner(page: Page, fresh_email: str):
    login_to_iam(page, fresh_email)

    client_id = f"e2e-{uuid.uuid4().hex[:8]}"
    register_application(page, name="Shared App", client_id=client_id)

    # Navigate to owner management.
    page.get_by_role("link", name="Manage owners").click()
    expect(page.locator("h1")).to_contain_text("Owners of Shared App")

    # DEMO_EMAIL is pre-seeded, so it exists and can be added.
    page.get_by_label("Email address").fill(DEMO_EMAIL)
    page.get_by_role("button", name="Add owner").click()
    expect(
        page.locator("dt.govuk-summary-list__key", has_text=DEMO_EMAIL)
    ).to_be_visible()

    # Remove the co-owner.
    page.get_by_role("button", name=f"Remove {DEMO_EMAIL}").click()
    expect(
        page.locator("dt.govuk-summary-list__key", has_text=DEMO_EMAIL)
    ).to_have_count(0)


def test_domain_restricted_application_blocks_user(
    page: Page, browser, fresh_email: str
):
    # Owner creates an application restricted to "allowed.com".
    login_to_iam(page, fresh_email)
    client_id = f"e2e-{uuid.uuid4().hex[:8]}"
    register_application(
        page,
        name="Restricted App",
        client_id=client_id,
        allowed_email_domains="allowed.com",
    )

    # A user with a blocked domain tries to authorize.
    blocked_email = f"e2e-{uuid.uuid4().hex[:8]}@blocked.com"
    ctx2 = browser.new_context()
    blocked_page = ctx2.new_page()
    login_to_iam(blocked_page, blocked_email)
    blocked_page.goto(f"{IAM}/o/authorize/{_pkce_params(client_id)}")
    expect(blocked_page.locator("h1")).to_contain_text(
        "You cannot access this application"
    )
    expect(blocked_page.get_by_text("Restricted App")).to_be_visible()
    ctx2.close()
