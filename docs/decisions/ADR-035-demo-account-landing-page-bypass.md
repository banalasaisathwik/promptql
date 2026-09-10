# ADR-035: Demo-account bypass for the landing-page demo flow

- Status: Accepted
- Date: 2026-08-29
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

ADR-034 built multi-user auth in four phases, all merged: Phase 1
(`users` table, Argon2id passwords, signed session cookie,
`register`/`login`/`logout`, `get_current_user`/`get_current_user_optional`
in `app/api/v1/auth_router.py`); Phase 2 (encrypted per-user
`credentials` table, `POST`/`GET`/`DELETE /v1/credentials` in
`app/api/v1/credentials_router.py`); Phase 3 (`get_github_connector`,
`get_github_code_evidence_source`, `get_jira_connector`, and
`get_incident_source` in `app/api/v1/connector_router.py` now resolve
per-request: an anonymous caller — `current_user is None` — still gets
the original `app.state` singleton fake/live connector unchanged, an
authenticated caller gets a connector built from *their own* decrypted
stored token via `from_stored_credential()`, or a 409 if they have not
connected that provider); and Phase 4 (investigation runs are
ownership-isolated per `user_id`). These four call sites in
`connector_router.py` are the *only* places anywhere in the backend that
turn a stored credential into a live connector — confirmed by searching
for every caller of `from_stored_credential`/`get_credential_repository`.

Separately, `docs/ARCHITECTURE.md` ("Public demo deployment") documents
an existing, unrelated safety mechanism: `PerIpRateLimitMiddleware`
(`app/api/v1/rate_limit.py`) is a per-process, per-IP fixed-window
limiter (10 requests/60s) applied only to `POST /v1/investigations` and
`POST /v1/investigations/extract-grounding`. This is request-volume
throttling, not an identity or credential control — it is unrelated to
which connector a request resolves to. (Note: the task description for
this ADR refers to this as "Phase 5." No such phase exists in ADR-034 or
anywhere in the codebase; this ADR cites the actual mechanism —
`PerIpRateLimitMiddleware` — by name instead.)

The frontend working tree already contains uncommitted, not-yet-ADR'd
scaffolding for the authenticated flow: `App.tsx` routes `/login` and
`/signup` to a new `WorkspaceAuthPage.tsx`, and `/connect` to a new
`ConnectToolsPage.tsx`, which is presumably where a real user connects
their own GitHub/Jira/Sentry credentials via `POST /v1/credentials`. The
root route `/` currently renders `InvestigationConsolePage` directly —
there is no landing page. This ADR's frontend piece adds one.

The owner's target: a public, unauthenticated visitor at `/` sees a
landing page with a "Try the Demo" button. Clicking it navigates to the
*real* login screen with a pre-provisioned demo account's email and
password already filled in — visible, one click to submit, a real login
actually happens. After login, the visitor sees the *real* Connect Tools
screen, with all three providers shown as "Connected — Demo Data," then
runs a real investigation against the existing checkout-500 fixture,
entirely inside the same authenticated UI a real user would use.

Because the demo account's password is visibly printed on a public page,
anyone can authenticate as this account directly, without ever clicking
the button — the login endpoint itself cannot be the security boundary
for this account. Whatever mechanism this ADR chooses has to make it
architecturally impossible for a session authenticated as this one
account to ever reach a real GitHub/Jira/Sentry API call, independent of
how many people are logged into it concurrently or what they type into
the UI.

## Decision drivers

- The safety property this account needs cannot rest on the password
  being secret (it isn't) or on the frontend behaving correctly (a
  visitor can call the API directly). It must be enforced in the same
  backend code path that already decides which connector a request gets
  — Phase 3's four dependency functions — not in a new, parallel path.
- Reuse Phase 3's existing per-request resolution and the existing
  anonymous-path fake singleton connectors rather than inventing new
  fake data or a second "demo mode" concept; CLAUDE.md's "reuse
  established abstractions before creating new ones" applies directly
  here, since a safe, working anonymous demo path already exists.
- The existing anonymous no-login demo path must stay provably
  unmodified — same invariant ADR-034 already committed to for Phases
  1-4. This ADR adds a second, authenticated way to reach the same fake
  connectors; it does not touch or replace the first.
- A schema column plus a new branch in four auth/credential-boundary
  functions, plus an API response shape change, are each Level 2 by
  CLAUDE.md's rubric (schema change, auth boundary, public API change).
- `PerIpRateLimitMiddleware` limits request *volume* per IP; it does
  nothing to limit what a request is authorized to do once admitted, so
  it cannot be the control that keeps this account safe and isn't relied
  on as one here.

## Options considered

### Bypass mechanism

#### Option A: `is_demo: bool` column on `users`, checked at connector-resolution time — chosen

An additive, `NOT NULL DEFAULT false` column. Each of the four Phase 3
dependency functions gains one additional branch, checked immediately
after the existing `current_user is None` anonymous check and before any
credential-repository lookup:

```python
if current_user is None or current_user.is_demo:
    yield request.app.state.github_connector
    return
```

`GET /v1/credentials` checks `current_user.is_demo` and returns a
synthetic all-connected response without querying
`CredentialRepository` at all. `POST`/`DELETE /v1/credentials` check it
first and return a rejection before touching the repository. The flag
lives on the same row FastAPI already loads via `get_current_user`/
`get_current_user_optional`, so no extra query is needed to check it.

#### Option B: Provision the demo account with a real credential row holding a non-functional/sentinel token, leave Phase 3 untouched

This is the option the owner already flagged as worse, and it is worse
for a concrete technical reason beyond "meaningless encrypted data
serving no purpose": Phase 3's connector-resolution code has no concept
of a "known-bad" token — it decrypts whatever is stored and calls
`from_stored_credential()` unconditionally. This account would then
issue a real outbound HTTP call to GitHub/Jira/Sentry on every
investigation step, with a token engineered to fail. The safety property
would rest entirely on that token never accidentally working (e.g., a
provider re-issuing a similar-looking token, or a copy-paste error
during provisioning that pastes a real token) — an unenforced runtime
assumption — instead of on code that structurally prevents the call from
being attempted. Rejected.

#### Option C: Hardcoded email allowlist (e.g., `current_user.email == DEMO_ACCOUNT_EMAIL`) instead of a schema column

Keeps the "is this a demo account" fact out of the `users` table
entirely and inside application constants/config. Two concrete problems:
auditing "which accounts are demo accounts" requires reading source
instead of querying data, and rotating or adding a second demo account
ever requires a code deploy instead of a data change. Rejected in favor
of a column that makes the fact part of queryable state, consistent with
how every other per-user property (`email`, `created_at`) already lives
on the row rather than in code.

### How `GET /v1/credentials` marks a demo response

#### Option 1: Add `source: Literal["real", "demo"]` to `CredentialConnectionResponse` — chosen, per owner's spec

Additive field on the existing per-provider response entry. Existing
(non-demo) responses populate `source="real"`, so the field is backward
compatible for every existing caller.

#### Option 2: Put `is_demo` on `UserResponse` instead, and let the frontend infer the "Demo Data" label itself

Simpler schema change (one boolean on the user object, already returned
by `login`/`register`, instead of a new field repeated per provider) and
would have been my default suggestion absent other input. Not chosen
because the owner's task description explicitly specifies the marker on
the credentials response ("`GET /v1/credentials` returns all three
providers as connected, with a `'source': 'demo'` marker"); recorded
here so the simpler alternative isn't silently lost if this is revisited
later.

## Repository owner reasoning

The owner specified, as resolved decisions rather than open questions:
`is_demo` is a plain boolean, default `false`, added via a strictly
additive migration alongside the existing `users` table shape from
ADR-034 Phase 1. When `current_user.is_demo` is true, all three Phase 3
connector-resolution functions return the existing anonymous fake
singleton connector — no new fake credential or fake connector is
introduced. `GET /v1/credentials` returns a synthetic three-provider
"connected, source=demo" response without querying the real
`credentials` table for this user at all. `POST`/`DELETE /v1/credentials`
return an explicit, specific rejection for this account, because there
is nothing real to connect or disconnect. The demo password is
intentionally not secret; safety comes entirely from the `is_demo`
bypass, not from the password being hard to guess or from restricting
who can reach the login form.

Two implementation details are not specified by the owner and are
proposed here as Level 1 choices, flagged for confirmation rather than
silently decided:

- **Provisioning the one demo row.** There is no admin surface in this
  application (correctly, per CLAUDE.md's scope discipline) and
  `POST /v1/auth/register` never sets `is_demo`. Proposal: a small,
  idempotent operational script (e.g.
  `services/api/scripts/seed_demo_account.py`) that upserts exactly one
  `is_demo=true` row with a fixed email/password, run manually once per
  environment the same way a migration is run — never exposed over
  HTTP, never reachable from `register`.
- **Rejection shape for `POST`/`DELETE /v1/credentials`.** Proposal: a
  new `ApiErrorCode.DEMO_ACCOUNT_CREDENTIALS_IMMUTABLE`, returned as
  `403 Forbidden` (an identity-based "this account categorically cannot
  do this," not a `409` state conflict like "you haven't connected this
  provider yet"), with message "Demo workspace credentials cannot be
  changed."

## Reasoning review

The core mechanism is sound and matches the pattern Phase 3 already
established: `current_user is None` and `current_user.is_demo` become
two branches that both resolve to the same pre-existing, already-safe
anonymous singleton connector, so no new "fake data" concept is
introduced anywhere — the only new code is the boolean check itself.
Because the check sits inside the four functions that are the sole
producers of a live connector from a stored credential (confirmed by
the `from_stored_credential`/`get_credential_repository` search above),
the "never reaches a real live call" property is enforced structurally,
not by convention: there is no second code path elsewhere that could
independently construct a GitHub/Jira/Sentry connector for this user.

One residual gap is worth naming explicitly rather than silently
carrying forward: this ADR does not add any protection against many
concurrent visitors sharing the single demo account's session/data at
once (e.g., one visitor's in-flight investigation being visible to, or
interleaved with, another's). ADR-034 Phase 4's ownership isolation
scopes runs by `user_id`, and every demo visitor shares one `user_id`,
so demo investigations are isolated from real users' investigations but
not from each other. This is a genuine, accepted limitation for a
public demo account, not a security hole (there is no real data behind
it to leak), and is recorded here rather than silently ignored.

## Decision

Implement the `is_demo` bypass as Option A: an additive
`is_demo BOOLEAN NOT NULL DEFAULT false` column on `users`; a new branch
in `get_github_connector`, `get_github_code_evidence_source`,
`get_jira_connector`, and `get_incident_source`
(`app/api/v1/connector_router.py`) that treats `current_user.is_demo`
identically to `current_user is None`, returning the existing
`app.state` fake singleton connector; `GET /v1/credentials`
(`app/api/v1/credentials_router.py`) short-circuits for a demo user to a
synthetic all-connected, `source="demo"` response without querying
`CredentialRepository`; `POST`/`DELETE /v1/credentials` short-circuit to
a `403 DEMO_ACCOUNT_CREDENTIALS_IMMUTABLE` rejection for a demo user
before touching `CredentialRepository`. `CredentialConnectionResponse`
gains an additive `source: Literal["real", "demo"]` field. The one demo
account row is provisioned by a manually-run, idempotent seed script,
never through a public endpoint.

Frontend: a new `LandingPage.tsx` becomes the `/` route in `App.tsx`
(replacing the current direct render of `InvestigationConsolePage` at
`/`), with a "Try the Demo" button that navigates to `/login` with the
demo account's email/password pre-filled in the existing
`WorkspaceAuthPage` — not auto-submitted, so the visitor sees the real
login happen. The existing `ConnectToolsPage` renders each `source="demo"`
provider with a distinct "Connected — Demo Data" label rather than the
label used for a real connection. Both pages already exist in the
working tree (uncommitted); this ADR extends them rather than
introducing new screens.

Explicitly out of scope for this ADR: any change to how
`register`/`login`/`logout` work for non-demo accounts; any change to
`PerIpRateLimitMiddleware` or rate limiting generally; any per-visitor
isolation within the shared demo account (see "Reasoning review"); and
any admin UI for managing `is_demo` accounts.

## Implementation update (2026-08-29)

**IMPLEMENTED**, all seven steps, validated end-to-end against a real
Neon Postgres test branch (see "Validation" below). One mechanism was
decided during implementation and is recorded here since it was not yet
named at Decision time above: a new `GET /v1/demo-account` route
(`app/api/v1/demo_account_router.py`), intentionally public and
unauthenticated, serves `{email, password}` read from
`PROMPTQL_DEMO_ACCOUNT_EMAIL`/`PROMPTQL_DEMO_ACCOUNT_PASSWORD` — the same
two environment variables `scripts/seed_demo_account.py` reads to
provision the row. This was chosen over a frontend build-time env var
because the frontend (Vercel) and backend (Render) already deploy
separately and the frontend already fetches all other state from the
backend at runtime rather than baking config into the Vite build; a
build-time var would have meant duplicating the password across two
deploy platforms' config and keeping them in sync by hand. A new
`DemoAccountSettings`/`DemoAccountConfigurationError` pair in
`app/config.py` mirrors the existing `AuthSettings` pattern, and a
missing configuration maps to the same sanitized `503
AUTH_PERSISTENCE_UNAVAILABLE` shape `CredentialConfigurationError`
already used, rather than a new error code for what is the same category
of failure (auth-adjacent configuration missing).

## Consequences

- New migration (next in sequence after
  `20260828_0011_add_workflow_run_user_ownership.py`) adding `is_demo`
  to `users`, independent of every other table's shape.
- `User` domain model (`app/auth/models.py`) gains `is_demo: bool`;
  `UserRepository`/`PostgresUserRepository`/`InMemoryUserRepository` and
  the `UserRow` database model carry it through `create_user`,
  `authenticate`, and `get_by_id`.
- `app/api/v1/connector_router.py`: one additional condition
  (`current_user.is_demo`) in four existing dependency functions; no
  other route or dependency in this file changes.
- `app/api/v1/credentials_router.py`: `store_credential`,
  `list_credentials`, and `delete_credential` each gain an early
  `current_user.is_demo` check; a new `ApiErrorCode` member
  (`DEMO_ACCOUNT_CREDENTIALS_IMMUTABLE`) on the existing `ApiError`
  shape in `app/api/v1/models.py`; `CredentialConnectionResponse` gains
  `source`.
- New `services/api/scripts/seed_demo_account.py`, run manually per
  environment; not part of the FastAPI app or any HTTP route.
- Frontend: new `LandingPage.tsx`; `App.tsx`'s `/` route changes from
  `InvestigationConsolePage` to `LandingPage`; `WorkspaceAuthPage`
  accepts pre-fill props; `ConnectToolsPage` renders the demo label
  variant when `source === "demo"`.
- `docs/ARCHITECTURE.md` is currently stale with respect to ADR-034
  itself — it still describes only Phase 1 as implemented, even though
  Phases 2-4 are merged (`1c7b799`, `0d91703`, `4ee3b00`) and touched no
  documentation. That gap predates this ADR and is called out here so it
  is not mistaken for something this ADR caused; closing it is a
  separate documentation task, not part of this decision.
- Not materially relevant to this ADR: password hashing, session
  signing, the planner/hypothesis/code-diagnosis LLM boundary, and
  non-demo investigation runs — none are touched.

## Invariants

- `current_user.is_demo` is checked in exactly the four functions listed
  above, each time immediately before any `CredentialRepository` access,
  and in no other location constructs a GitHub/Jira/Sentry connector
  from a stored credential.
- No code path decrypts, reads, or constructs a connector from a real
  stored credential for a user where `is_demo` is true, under any
  request, ever.
- The existing anonymous (`current_user is None`) demo path's behavior,
  and every route/dependency untouched by this ADR, are byte-for-byte
  unchanged.
- `is_demo` is never settable through `POST /v1/auth/register` or any
  other HTTP-reachable path; it is only ever set by the manually-run
  seed script.
- A demo account can never have a row in `credentials` written for it
  through the API (`POST /v1/credentials` rejects before reaching
  `CredentialRepository.store_credential`).

## Validation

`uv run python -m unittest discover -s tests -v` from `services/api`,
with new coverage for: each of the four connector-resolution functions
returning the anonymous singleton when `is_demo=true` (not attempting
any stored-credential lookup — asserted via a `CredentialRepository`
test double that fails the test if invoked); `GET /v1/credentials` for a
demo user returning all three providers `connected=true,
source="demo"` without a `CredentialRepository` call;
`POST`/`DELETE /v1/credentials` for a demo user returning `403
DEMO_ACCOUNT_CREDENTIALS_IMMUTABLE` without a `CredentialRepository`
call; the existing Phase 1-4 suite passing unmodified, proving the
anonymous and real-authenticated paths are unaffected. Frontend:
`bun run test:web` covering `LandingPage` rendering and the "Try the
Demo" navigation-with-prefill, and `ConnectToolsPage` rendering the
demo-data label when `source === "demo"`.

**Confirmed (2026-08-29):** full backend suite 628 tests, OK, 14 skipped
(pre-existing PostgreSQL-integration skips, unrelated); frontend 55
tests pass, `bunx tsc -b --noEmit` exit 0. Additionally verified live
against a dedicated Neon test branch (never the application branch):
`scripts/seed_demo_account.py` run twice confirmed idempotent (create,
then no-op); the demo account logged in through the real
`POST /v1/auth/login` and `GET /v1/credentials` returned all three
providers `connected=true, source="demo"`; a real investigation was
started and completed through the actual `POST /v1/investigations` path
using `app.state`'s `Fake*` connector singletons, which were confirmed
to hold no HTTP client at all (no transport for a live call to travel
over, independent of any application logic); and a freshly registered
non-demo user with no stored credential was confirmed still rejected
with the exact original `409` and message. The investigation's own LLM
calls went to the real, already-configured Groq provider (an explicit,
approved choice for that one verification run, unrelated to this ADR's
connector-bypass mechanism) — GitHub/Jira/Sentry access is the only
thing this ADR bypasses, and no live call to any of those three
providers was possible or attempted.

## Reconsideration triggers

Revisit per-visitor isolation within the shared demo account (see
"Reasoning review") if concurrent public demo traffic makes
cross-visitor interference (shared investigation history, ownership
scoped only to one shared `user_id`) a real observed problem rather than
a theoretical one. Revisit the manual seed-script provisioning approach
if a second demo account, or a rotating/expiring demo account, is ever
needed — that would justify a small provisioning surface instead of a
one-off script. Revisit `DEMO_ACCOUNT_CREDENTIALS_IMMUTABLE` as `403`
versus another status code if a frontend consumer needs to distinguish
this rejection from other `403`s it does not yet produce.
