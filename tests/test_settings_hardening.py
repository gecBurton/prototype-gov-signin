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


def test_login_code_rate_limit_tightened_without_clobbering_defaults():
    """The login-by-code request keeps hourly per-recipient and per-IP caps,
    and our partial override must not drop allauth's other rate limits."""
    from allauth.account import app_settings as account_settings

    rate_limits = account_settings.RATE_LIMITS
    assert rate_limits["request_login_code"] == "20/m/ip,3/m/key,10/h/key"
    # allauth merges (ret.update) — its other defaults must survive.
    assert rate_limits["login"] == "30/m/ip"
    assert rate_limits["reset_password"]
