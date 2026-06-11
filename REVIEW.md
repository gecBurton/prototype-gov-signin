# Project review — 2026-06-11

Overall this is in very good shape for a prototype: the code is clean and idiomatic
Django, the README is excellent, client secrets are hashed with the raw value shown
exactly once via a session stash, the grant type and algorithm are locked down with DB
check constraints (not just form validation), the domain suffix matching is implemented
correctly (label-based splitting, so `evilcabinetoffice.gov.uk` cannot spoof
`cabinetoffice.gov.uk`), and there is solid coverage — 48 unit tests plus Playwright
integration tests, with CI checking formatting and missing migrations.

Findings in priority order.

## Security / correctness

### 1. Deleting a team silently removes all access restrictions on its apps
`Application.team` uses `on_delete=SET_NULL` (`iam/users/models.py`), and
`_is_domain_allowed` returns `True` when `team is None` (`iam/users/views.py`). So
deleting a team leaves its applications live, unmanageable by anyone except admins, and
open to **every** authenticated user — a fail-open default on the security boundary this
service exists to enforce. Use `on_delete=PROTECT` (cannot delete a team that still owns
apps), or make team-less apps fail closed.

### 2. Domain rules only apply at authorization time
Removing a domain does not revoke existing access/refresh tokens or RP sessions — a
deprovisioned user keeps working until their tokens expire. Probably acceptable for a
prototype, but worth a sentence in the README so the limitation is deliberate rather
than discovered.

### 3. A team can be orphaned by its own members
`TeamMemberRemove` lets any member remove any other member, including the last one. The
team and its apps keep running but become manageable only via Django admin. Consider
blocking removal of the final member.

### 4. Member-add error messages enable user enumeration
"No user found with email X" vs "X is already a team member" (`TeamDetail.post`) tells a
logged-in user which emails have accounts. Low risk for an internal tool, but trivially
avoidable with a generic message.

### 5. `.env` contains a real Google OAuth client secret
Correctly gitignored and not in git history, so fine locally — just be aware it is
plaintext on disk; rotate it if the machine or a backup is ever shared.

## Robustness / deployment

### 6. `AutoEnrollRequestLoginCodeForm` reimplements allauth internals
It manually consumes the rate limit and sets `self._user` (`iam/users/forms.py`),
duplicating the parent's `clean_email` logic. This will break silently if an allauth
upgrade changes those internals. The README already notes that finishing Google social
login would remove the need for this form — that is the better path; until then the
auto-enrol tests are the safety net, so keep allauth pinned reasonably tightly.

### 7. The Docker image cannot serve static files in production
The image never runs `collectstatic`, but `DEBUG=false` uses whitenoise's manifest
storage, which 500s on missing manifests. It works today only because compose runs
`runserver` with `DEBUG=true` and the Procfile's release phase does collectstatic
(Heroku-style). If the image is ever deployed directly, it breaks — add `collectstatic`
to the Dockerfile build or the container entrypoint.

### 8. Minor prod-hardening gaps
No `SECURE_HSTS_SECONDS` (the rest of the `DEBUG=false` block in `iam/settings.py` is
good). Worth a one-off run of `manage.py check --deploy`.

## Nits

- The uncommitted change in `team_list.html` puts body copy above the `<h1>` — GOV.UK
  Design System pages put the page heading first, with lead-in text after it.
- `pyproject.toml` still says `description = "Add your description here"`.
- `.idea/` is committed; most teams gitignore it.
- `email_verified: True` is hardcoded in the validator (`iam/validators.py`) — true
  today since both login flows verify email, but a comment explaining why would protect
  against a future flow that does not.

The single most important fix is #1 — a one-line model change plus a migration that
converts a silent fail-open into an explicit error.
