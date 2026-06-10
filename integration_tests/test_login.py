from conftest import (
    DEMO_EMAIL,
    GRAFANA,
    IAM,
    clear_mailbox,
    fetch_login_code,
    login_to_iam,
)
from playwright.sync_api import Page, expect


def test_grafana_login_via_iam(page: Page):
    clear_mailbox()

    # 1. Land on Grafana and click the IAM login button
    page.goto(f"{GRAFANA}/login")
    page.get_by_text("Sign in with IAM").click()

    # 2. Grafana → IAM /o/authorize/ → IAM /accounts/login/
    page.wait_for_url(f"{IAM}/accounts/login/**")

    # 3. Click the email-code link — this navigates to /accounts/login/code/
    #    with the next param preserved in the URL
    page.get_by_role("link", name="Sign in with a code by email instead").click()
    page.wait_for_url(f"{IAM}/accounts/login/code/**")
    page.get_by_label("Email").fill(DEMO_EMAIL)
    page.get_by_role("button", name="Request Code").click()

    # 4. Wait for the code confirmation page
    page.wait_for_url(f"{IAM}/accounts/login/code/confirm/**")

    # 5. Retrieve code from Mailpit and submit it
    code = fetch_login_code(DEMO_EMAIL)
    page.get_by_placeholder("Code").fill(code)
    page.get_by_role("button", name="Confirm").click()

    # 6. allauth → /o/authorize/ → Grafana callback → Grafana dashboard
    page.wait_for_url(f"{GRAFANA}/**", timeout=15_000)
    expect(page).not_to_have_url(f"{GRAFANA}/login")


def test_new_user_auto_enrols_via_grafana(page: Page, fresh_email: str):
    # Same flow as above but with an email that has never been seen before.
    # The account is created automatically by the auto-enrolment form.
    page.goto(f"{GRAFANA}/login")
    page.get_by_text("Sign in with IAM").click()
    page.wait_for_url(f"{IAM}/accounts/login/**")
    page.get_by_role("link", name="Sign in with a code by email instead").click()
    page.wait_for_url(f"{IAM}/accounts/login/code/**")
    page.get_by_label("Email").fill(fresh_email)
    page.get_by_role("button", name="Request Code").click()
    page.wait_for_url(f"{IAM}/accounts/login/code/confirm/**")
    code = fetch_login_code(fresh_email)
    page.get_by_placeholder("Code").fill(code)
    page.get_by_role("button", name="Confirm").click()
    page.wait_for_url(f"{GRAFANA}/**", timeout=15_000)
    expect(page).not_to_have_url(f"{GRAFANA}/login")


def test_return_user_can_login_again(page: Page, browser, fresh_email: str):
    # First visit — account is auto-created.
    login_to_iam(page, fresh_email)

    # Second visit in a fresh browser context — account already exists,
    # user should still receive a code and complete login normally.
    clear_mailbox()
    ctx2 = browser.new_context()
    page2 = ctx2.new_page()
    login_to_iam(page2, fresh_email)
    expect(page2).to_have_url(f"{IAM}/")
    ctx2.close()


def test_logout_via_grafana_lands_on_iam(page: Page, fresh_email: str):
    # Complete a full Grafana login as a new user.
    page.goto(f"{GRAFANA}/login")
    page.get_by_text("Sign in with IAM").click()
    page.wait_for_url(f"{IAM}/accounts/login/**")
    page.get_by_role("link", name="Sign in with a code by email instead").click()
    page.wait_for_url(f"{IAM}/accounts/login/code/**")
    page.get_by_label("Email").fill(fresh_email)
    page.get_by_role("button", name="Request Code").click()
    page.wait_for_url(f"{IAM}/accounts/login/code/confirm/**")
    code = fetch_login_code(fresh_email)
    page.get_by_placeholder("Code").fill(code)
    page.get_by_role("button", name="Confirm").click()
    page.wait_for_url(f"{GRAFANA}/**", timeout=15_000)

    # Sign out of Grafana — Grafana redirects to IAM's logout URL.
    page.goto(f"{GRAFANA}/logout")
    page.wait_for_url(f"{IAM}/**", timeout=10_000)

    # allauth may show a logout confirmation page; submit it if present.
    signout_btn = page.get_by_role("button", name="Sign out")
    if signout_btn.is_visible():
        signout_btn.click()
        page.wait_for_url(f"{IAM}/**")

    # Protected IAM pages should now require re-authentication.
    page.goto(f"{IAM}/o/teams/")
    page.wait_for_url(f"{IAM}/accounts/login/**")
