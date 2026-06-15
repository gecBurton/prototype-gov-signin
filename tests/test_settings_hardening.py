"""Settings-resolution guards.

The Google endpoint overrides (GOOGLE_AUTHORIZE_URL etc.) repoint allauth's
"Google" provider. Combined with SOCIALACCOUNT_EMAIL_AUTHENTICATION, an
attacker-controlled value would let any IdP mint a verified login for any
address. They must therefore be honoured only under DEBUG and ignored in
production, even when the env vars are present.

This resolves at settings-import time, so it is checked in a subprocess with a
clean environment rather than via override_settings.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

IAM_DIR = Path(__file__).resolve().parent.parent / "iam"

_PRINT_AUTHORIZE_URL = (
    "import django; django.setup();"
    "from django.conf import settings;"
    "print(settings.SOCIALACCOUNT_PROVIDERS['google'].get('AUTHORIZE_URL'))"
)


def _resolved_authorize_url(debug):
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "settings",
        "PYTHONPATH": str(IAM_DIR),
        "SECRET_KEY": "settings-test-key",
        "DEBUG": debug,
        # Both required under DEBUG=false; irrelevant to what this test asserts.
        "ALLOWED_HOSTS": "iam.example.gov.uk",
        "OIDC_RSA_PRIVATE_KEY": "dummy-key",
        "GOOGLE_CLIENT_ID": "id",
        "GOOGLE_CLIENT_SECRET": "secret",
        "GOOGLE_AUTHORIZE_URL": "http://attacker.example/auth",
    }
    result = subprocess.run(
        [sys.executable, "-c", _PRINT_AUTHORIZE_URL],
        env=env,
        cwd=str(IAM_DIR),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize(
    "debug,expected",
    [
        ("true", "http://attacker.example/auth"),  # honoured for local Dex
        ("false", "None"),  # ignored in production — real Google is used
    ],
)
def test_google_endpoint_override_only_honoured_in_debug(debug, expected):
    assert _resolved_authorize_url(debug) == expected


def _import_settings(env_overrides):
    """Import settings in a clean subprocess; return the CompletedProcess.

    Settings resolution (ALLOWED_HOSTS, the Google overrides) happens at import
    time, so it must be exercised out-of-process rather than via override_settings.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DJANGO_SETTINGS_MODULE": "settings",
        "PYTHONPATH": str(IAM_DIR),
        "SECRET_KEY": "settings-test-key",
        # Satisfy the database and OIDC-key guards by default so each test
        # isolates the one guard it targets; django.setup() configures settings
        # without opening a connection or signing a token. A test that targets
        # the OIDC guard overrides OIDC_RSA_PRIVATE_KEY to "" to remove it.
        "POSTGRES_HOST": "localhost",
        "OIDC_RSA_PRIVATE_KEY": "dummy-key",
        **env_overrides,
    }
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        env=env,
        cwd=str(IAM_DIR),
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "env,returncode,in_stderr",
    [
        # Production with no ALLOWED_HOSTS must refuse to start, rather than
        # booting and then 400ing every request.
        ({"DEBUG": "false"}, 1, "ALLOWED_HOSTS"),
        # Production with ALLOWED_HOSTS set starts fine.
        ({"DEBUG": "false", "ALLOWED_HOSTS": "iam.example.gov.uk"}, 0, ""),
        # Under DEBUG it stays optional (Django falls back to localhost).
        ({"DEBUG": "true"}, 0, ""),
    ],
)
def test_allowed_hosts_required_in_production(env, returncode, in_stderr):
    result = _import_settings(env)
    assert result.returncode == returncode, result.stderr
    assert in_stderr in result.stderr


@pytest.mark.parametrize(
    "env,returncode,in_stderr",
    [
        # A key supplied via the env var satisfies the check in production.
        (
            {
                "DEBUG": "false",
                "ALLOWED_HOSTS": "iam.example.gov.uk",
                "OIDC_RSA_PRIVATE_KEY": "dummy-key",
            },
            0,
            "",
        ),
        # Under DEBUG it stays optional (dev generates a key separately).
        ({"DEBUG": "true"}, 0, ""),
    ],
)
def test_oidc_signing_key_present_or_optional(env, returncode, in_stderr):
    result = _import_settings(env)
    assert result.returncode == returncode, result.stderr
    assert in_stderr in result.stderr


def test_oidc_signing_key_required_in_production():
    """With no key (env var or oidc.key file) the service must refuse to start,
    rather than booting and only failing when the first token is signed.

    settings.py falls back to reading BASE_DIR/oidc.key, which a dev machine
    has, so hide it for the duration of this check to exercise the absent path.
    """
    key_file = IAM_DIR / "oidc.key"
    hidden = key_file.with_suffix(".key.hidden-for-test")
    if key_file.exists():
        key_file.rename(hidden)
    try:
        result = _import_settings(
            {
                "DEBUG": "false",
                "ALLOWED_HOSTS": "iam.example.gov.uk",
                # Override the helper's default dummy key back to absent.
                "OIDC_RSA_PRIVATE_KEY": "",
            }
        )
    finally:
        if hidden.exists():
            hidden.rename(key_file)
    assert result.returncode == 1, result.stderr
    assert "OIDC" in result.stderr


def test_login_code_rate_limit_tightened_without_clobbering_defaults():
    """The login-by-code request keeps hourly per-recipient and per-IP caps,
    and our partial override must not drop allauth's other rate limits."""
    from allauth.account import app_settings as account_settings

    rate_limits = account_settings.RATE_LIMITS
    assert rate_limits["request_login_code"] == "20/m/ip,3/m/key,10/h/key"
    # allauth merges (ret.update) — its other defaults must survive.
    assert rate_limits["login"] == "30/m/ip"
    assert rate_limits["reset_password"]
