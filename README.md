> [!IMPORTANT]  
> This private project is just-for-fun, no part of it is used or otherwise endorsed in UK Gov


## prototype-gov-signin — Django OIDC Identity Provider

A Django service that acts as an OpenID Connect identity provider for internal tools. Teams register their applications here and get a client ID and secret; their applications then authenticate users via the standard OIDC authorization code flow.

Built on two libraries that each own one half of the authentication picture.

---

## django-allauth — how users log in to *this* service

[django-allauth](https://github.com/pennersr/django-allauth) handles the inbound side: getting a human being authenticated into the IAM service itself.

This project uses **login-by-code** (passwordless email). A user submits their email address, receives a one-time code, and enters it to complete sign-in. There is no password.

```
user visits /o/teams/
  → redirected to /accounts/login/
  → submits email at /accounts/login/code/
  → receives code by email (via Mailpit in dev)
  → submits code at /accounts/login/code/confirm/
  → authenticated, returned to original destination
```

**Auto-enrolment.** On a fresh database no accounts exist. Rather than requiring a separate sign-up step, the service automatically creates an account the first time an email address is submitted. This is implemented in `iam/users/forms.py` via a custom `RequestLoginCodeForm` subclass registered under `ACCOUNT_FORMS` in settings. The created account has no usable password and a verified email address.

**No usernames.** The custom `User` model has no username field; the email address is the identifier (`USERNAME_FIELD = "email"`). allauth is configured accordingly with `ACCOUNT_USER_MODEL_USERNAME_FIELD = None`.

**Relevant settings:**

```python
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_FORMS = {"request_login_code": "users.forms.AutoEnrollRequestLoginCodeForm"}
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
```

**Google social login** is partially configured (`allauth.socialaccount.providers.google` is installed, `SOCIALACCOUNT_PROVIDERS` is set). Completing this would let users sign in with their Cabinet Office Google account instead of the email code flow — allauth handles user creation on first login automatically, removing the need for the custom form.

---

## django-oauth-toolkit — how *other services* authenticate their users

[django-oauth-toolkit](https://github.com/jazzband/django-oauth-toolkit) (DOT) handles the outbound side: making this Django app an OAuth 2.0 / OIDC authorization server that other applications can trust.

When a service like Grafana needs to know who a user is, it redirects them here. DOT issues a short-lived authorization code, which the service exchanges for an access token and ID token. The ID token contains the user's identity (sub, email, etc.) signed with this server's private RSA key.

```
user visits Grafana
  → Grafana redirects to /o/authorize/?client_id=grafana&...
  → user authenticates via allauth (above)
  → user sees consent screen (or auto-approves)
  → Grafana receives authorization code
  → Grafana POSTs to /o/token/ to exchange for tokens
  → Grafana calls /o/userinfo/ to get user claims
  → user is logged in to Grafana
```

DOT exposes the standard OIDC endpoints:

| Endpoint | Purpose |
|---|---|
| `/o/authorize/` | Authorization endpoint — starts the flow |
| `/o/token/` | Token endpoint — exchanges code for tokens |
| `/o/userinfo/` | Returns claims for the bearer token |
| `/o/.well-known/openid-configuration/` | Discovery document |
| `/o/jwks/` | Public keys for token verification |

**Teams and application management.** DOT provides base views for registering and managing OAuth clients (applications). This project extends them: applications belong to a `Team` (models in `iam/users/models.py`), and users manage their teams' applications, members, and allowed email domains under `/o/teams/` (views in `iam/users/views.py`). Users and teams are many-to-many via a `Membership` model.

**Domain restriction.** Each team can whitelist email domains (`AllowedEmailDomain`), which apply to all of its applications. Matching is by suffix, so allowing `cabinetoffice.gov.uk` also admits `digital.cabinetoffice.gov.uk`. A team with no domains configured (or an application with no team) allows all users. The custom `AuthorizationView` in `iam/users/views.py` intercepts the authorize endpoint and returns 403 if the authenticated user's email domain is not allowed. This check runs on both GET (consent screen) and POST (form submission).

**Relevant settings:**

```python
OAUTH2_PROVIDER_APPLICATION_MODEL = "users.Application"
OAUTH2_PROVIDER = {
    "OIDC_ENABLED": True,
    "OIDC_RSA_PRIVATE_KEY": ...,   # loaded from oidc.key or OIDC_RSA_PRIVATE_KEY env var
    "OAUTH2_VALIDATOR_CLASS": "validators.OIDCValidator",
    "SCOPES": {"openid": "...", "profile": "...", "email": "..."},
}
```

The RSA private key (`oidc.key`) is used to sign ID tokens. Generate one with:

```
openssl genrsa -out iam/oidc.key 4096
```

---

## Running locally

Prerequisites: [Docker](https://docs.docker.com/get-docker/) and [uv](https://docs.astral.sh/uv/).

First generate the OIDC signing key (one-off — the file is gitignored, and `docker compose` bind-mounts it into the container):

```
openssl genrsa -out iam/oidc.key 4096
```

Then start the stack:

```
make up
```

This starts:
- **iam** — the Django service on port 8000
- **db** — Postgres 17
- **mailpit** — catches outbound email; web UI at http://localhost:8025
- **grafana** — a pre-configured demo relying party at http://localhost:3000

On first start, `manage.py create_demo_apps` seeds a demo user and a Grafana OAuth application. Log in to Grafana with "Sign in with IAM", complete the email code flow in Mailpit, and you will land in Grafana authenticated.

## Configuration

The `SECRET_KEY` environment variable is always required — there is no fallback and the service refuses to start without one. `DEBUG` defaults to **false**; when false, HTTPS-only cookies and SSL redirect are enabled. The dev entry points (`docker compose up`, `make run`, pytest) set `DEBUG=true` and an insecure dev `SECRET_KEY` for you, so a deployed instance only needs to set a real `SECRET_KEY` and leave `DEBUG` unset.

Outbound email picks a backend from the environment: if `GOVUK_NOTIFY_API_KEY` is set, codes are sent via GOV.UK Notify; otherwise if `EMAIL_HOST` is set, plain SMTP is used (docker compose points this at Mailpit); otherwise emails are printed to the console.

## Running tests

### Unit tests

```
make install
make test
```

Tests use SQLite (no Postgres needed) and `locmem` email backend. The full OIDC flow is covered in `iam/tests/test_oidc_flow.py`.

### Integration tests (Playwright)

End-to-end browser tests in `integration_tests/` drive the full docker compose stack: login by email code (reading the code from Mailpit's API), the Grafana OIDC flow, and team/application management. They need the stack running (see [Running locally](#running-locally)):

```
make install-integration   # one-off: installs the integration deps + Chromium
make up                    # in a separate terminal, if not already running
make integration-test
```

The tests seed data (teams, users) by shelling into the running `iam` container with `docker compose exec`, so they must be run from the repository root against the compose stack — not against a bare `make run` server.

Both suites run in CI (`.github/workflows/ci.yml`); the integration job builds the compose stack on the runner and generates a throwaway `oidc.key`.
