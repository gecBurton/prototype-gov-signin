import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page

REPO_ROOT = Path(__file__).resolve().parent.parent

GRAFANA = "http://localhost:3000"
IAM = "http://localhost:8000"
MAILPIT_API = "http://localhost:8025/api/v1"

DEMO_EMAIL = "demo@example.com"


def clear_mailbox():
    requests.delete(f"{MAILPIT_API}/messages")


def fetch_login_code(email: str, timeout: int = 15) -> str:
    """Poll Mailpit until an email arrives for the given address and return the login code."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(f"{MAILPIT_API}/messages")
        for msg in resp.json().get("messages", []):
            if any(r["Address"] == email for r in msg.get("To", [])):
                body = requests.get(f"{MAILPIT_API}/message/{msg['ID']}").json()
                match = re.search(
                    r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", body.get("Text", "")
                )
                if match:
                    return match.group(1)
        time.sleep(0.5)
    raise TimeoutError(f"No login code email received for {email} within {timeout}s")


def login_to_iam(page: Page, email: str) -> None:
    """Complete the IAM login-by-code flow, auto-enrolling if the account is new."""
    page.goto(f"{IAM}/accounts/login/code/")
    page.get_by_label("Email").fill(email)
    page.get_by_role("button", name="Request Code").click()
    page.wait_for_url(f"{IAM}/accounts/login/code/confirm/**")
    code = fetch_login_code(email)
    page.get_by_placeholder("Code").fill(code)
    page.get_by_role("button", name="Confirm").click()
    page.wait_for_url(f"{IAM}/**")


def create_team(name: str, *member_emails: str) -> None:
    """Create a team with the given members directly in the app's database.

    There is no UI for creating teams, so this shells into the running
    iam container (requires `make up`).
    """
    lines = [
        "from django.contrib.auth import get_user_model",
        "from users.models import Team",
        f"team = Team.objects.create(name={name!r})",
    ]
    for email in member_emails:
        lines += [
            f"user, _ = get_user_model().objects.get_or_create(email={email!r})",
            "user.teams.add(team)",
        ]
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "iam",
            "sh",
            "-c",
            "cd iam && uv run python manage.py shell",
        ],
        input="\n".join(lines),
        text=True,
        check=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )


@pytest.fixture
def fresh_email():
    return f"e2e-{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture
def team_name(fresh_email):
    """A team that the fresh_email user belongs to."""
    name = f"e2e-team-{uuid.uuid4().hex[:8]}"
    create_team(name, fresh_email)
    return name


@pytest.fixture(autouse=True)
def empty_mailbox():
    clear_mailbox()
    yield
