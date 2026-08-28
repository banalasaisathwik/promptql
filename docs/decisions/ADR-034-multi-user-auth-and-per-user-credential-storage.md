# ADR-034: Multi-user auth and per-user credential storage

- Status: Accepted
- Date: 2026-08-28
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

PromptQL is currently a single-tenant, anonymous-by-design application.
Every HTTP request operates against the same server-wide state: GitHub,
Jira, and Sentry connectors are each constructed once from environment
variables (`GitHubSettings.from_environment()`, `JiraSettings`,
`SentrySettings`) at `create_app()`/`lifespan()` time and stored on
`app.state` (`services/api/app/main.py`); every request receives the same
`app.state.github_connector`, `app.state.jira_connector`, and
`app.state.incident_source` through the `get_github_connector`,
`get_jira_connector`, and `get_incident_source` dependencies
(`services/api/app/api/v1/connector_router.py`). There is no concept of a
user, no login, and no per-caller credential. `docs/ARCHITECTURE.md`
("Not implemented") records this explicitly: "GitHub, Jira, or Sentry
OAuth/app authentication or any multi-tenant connector credential model"
does not exist today, and "Public demo deployment" documents that
provider/connector mode selection is process-wide, not request-scoped, by
construction.

The owner's target end state is that each user authenticates and supplies
their own GitHub/Jira/Sentry credentials, so investigations run against a
given user's own repositories and issue trackers instead of one shared
demo token set. That end state requires several materially separate
pieces of engineering: password-based identity, session handling,
encrypted-at-rest credential storage, and rewiring `get_github_connector`/
`get_jira_connector`/`get_incident_source` from process-lifetime `app.state`
singletons to per-request, per-user resolution. Attempting all of it as one
change would mix a foundational identity primitive with a much larger,
independently risky rework of the connector dependency graph. This ADR
resolves the schema and identity core only (Phase 1) and records the
remaining phases as deferred, not silently dropped.

This is narrower than "full multi-tenancy" or an "enterprise OAuth
platform" (both listed as explicit non-goals in `docs/ARCHITECTURE.md`):
there are no organizations, teams, roles, or cross-user data isolation
concerns here — one user has one account and, eventually, their own
connector credentials. The owner is the authority that decides when a
milestone justifies departing from a default non-goal; this ADR is that
decision for user identity specifically, not a blanket reopening of
multi-tenancy as a non-goal.

## Decision drivers

- The existing anonymous demo path (every route in `connector_router.py`,
  the process-wide connector singletons, the public Vercel/Render
  deployment described in `docs/ARCHITECTURE.md`) must keep working
  unmodified throughout this phase. Nothing about how an anonymous request
  is served today may change.
- Password storage must resist offline brute force after a hypothetical
  database leak. Nothing in the Python standard library provides a
  memory-hard, adaptive password KDF; a purpose-built library is required
  ("Dependencies" below).
- A session mechanism must be tamper-evident (a client must not be able to
  mint or extend its own session) and must expire, without adding a new
  stateful store (Redis, a `sessions` table) before there is a concrete
  requirement for server-side revocation. CLAUDE.md's scope discipline
  already defers Redis; nothing in Phase 1 needs it.
- Every new production dependency requires the standard due-diligence
  write-up (CLAUDE.md "Dependencies") before it is added.
- The migration must be strictly additive: a new `users` table beside the
  existing `workflow_runs`, `workflow_steps`, and `repository_fact_recurrence`
  tables, with no change to any existing table's shape. The existing test
  suite should require zero test-file edits as a direct consequence.
- Per-user GitHub/Jira/Sentry credential storage is deliberately out of
  scope for this ADR's implementation, even though it motivates the work:
  it needs its own decision on encryption-at-rest, key management, and how
  `get_github_connector`/`get_jira_connector`/`get_incident_source` move
  from singleton to per-request resolution — each a Level 2 decision in its
  own right.

## Options considered

### Password hashing

#### Option A: `hashlib.pbkdf2_hmac` (Python standard library, no new dependency)

PBKDF2 needs no new dependency and is FIPS-approved, but it is not
memory-hard: its cost is pure CPU iteration, which parallelizes cheaply on
GPUs/ASICs. Current OWASP password-storage guidance recommends Argon2id
over PBKDF2 whenever it is available. Rejected: it is available today
(stdlib) but is the weaker choice for a project whose explicit purpose
includes learning current security practice, not just avoiding a
dependency.

#### Option B: `bcrypt`

Mature and extremely widely deployed. Two concrete downsides: it silently
truncates input at 72 bytes with no error (a real footgun for
non-ASCII/long passwords, and one users cannot detect without testing for
it), and like PBKDF2 it is not memory-hard, so it remains cheaper to
brute-force at scale on parallel hardware than a memory-hard function at
equivalent wall-clock cost. Rejected in favor of a memory-hard option.

#### Option C: `argon2-cffi` (Argon2id) — chosen

Argon2 won the 2015 Password Hashing Competition and is OWASP's current
top recommendation for new password storage. `argon2-cffi` provides CFFI
bindings to the reference C implementation, is actively maintained, has no
silent-truncation behavior, and its `PasswordHasher` API embeds algorithm
version and cost parameters in the stored hash string itself, so cost
parameters can be raised later without a schema change or a migration of
existing hashes (verification reads the embedded parameters; only a
future login naturally re-hashes under new parameters, which Phase 1 does
not yet implement but does not preclude).

### Session mechanism

#### Option A: Stateful server-side sessions (new `sessions` table, random opaque token, DB lookup per request)

Requires its own table, migration, and an expiry/cleanup story on top of
Phase 1's actual requirement, which is simply proving `user_id` on a
request. Every future authenticated request would cost an extra DB round
trip purely for session validation. Rejected as more machinery than Phase
1 needs; revisit only if server-side revocation-before-expiry becomes a
real requirement (see "Reconsideration triggers").

#### Option B: JWT

Self-contained claims are unnecessary here — this is a same-origin cookie
whose only job is identifying `user_id` to this one API, not a token
handed to other services. JWT libraries carry well-known misuse surface
(`alg: none`, algorithm-confusion attacks) that a general-purpose JWT
dependency would import even though none of that flexibility is used.
Rejected as the wrong tool for a single-service, same-origin cookie.

#### Option C: `itsdangerous` signed, timestamped opaque token in a cookie — chosen

`itsdangerous` (originally built for Flask sessions) does exactly this:
`URLSafeTimedSerializer` HMAC-signs an arbitrary string, and `.loads(...,
max_age=...)` rejects a tampered signature or an expired token in one
call. It is stateless (no new table, no store), the API surface is small
enough to review completely, and it has no cryptographic-agility footguns
comparable to JWT's `alg` field. The cookie itself is `httponly`,
`secure`, and `samesite=lax`, and carries only `user_id` — no claims, no
role, no credential.

## Repository owner reasoning

The owner specified the following as resolved decisions, not open
questions for this ADR: the `users` table holds exactly `id` (UUID
primary key), `email` (unique), `password_hash`, and `created_at` — no
`email_verified` and no password-reset-token columns in this phase, since
neither has a concrete consumer yet and both are real schema decisions
(verification-flow shape, token expiry/rotation) better made when a
milestone actually needs them, not spoken for in advance. The two new
dependencies are `argon2-cffi` and `itsdangerous`, added under the
existing "Dependencies" due-diligence process. The session cookie is
signed, `httponly`, `secure`, `samesite=lax`, and holds only `user_id`.
`register`/`login`/`logout` routes and a `get_current_user` dependency are
built in this phase, but `get_current_user` is explicitly *not* threaded
into `get_github_connector`, `get_jira_connector`, `get_incident_source`,
or any existing route yet — those stay completely untouched, so the
anonymous demo path is unaffected by this phase by construction, not by
incidental omission.

## Reasoning review

The scoping is sound: nothing about the anonymous path changes because no
existing dependency function or route is edited, and the new `users`
table has no foreign key from any existing table, so no existing row's
shape or meaning changes either. Two implementation-relevant risks surface
that the owner's decision doesn't resolve on its own and are recorded here
rather than silently handled:

1. **`secure=True` requires HTTPS.** Browsers drop a `Secure`-flagged
   cookie set over plain HTTP. The Render/Vercel public deployment already
   terminates TLS, so production is unaffected, but a local `bun run
   dev:web` session talking to a local `uv run fastapi dev` backend over
   plain `http://localhost` will not receive the cookie at all. This ADR
   keeps `secure=True` unconditionally, exactly as decided, rather than
   silently branching on an environment flag that was not requested; local
   HTTPS (e.g., a local TLS proxy) is required to exercise the cookie flow
   end-to-end outside of automated tests, which bypass the browser cookie
   jar entirely and are unaffected.
2. **No CORS middleware exists today** (`docs/ARCHITECTURE.md`, "Public
   demo deployment": "no `CORSMiddleware` was added to `main.py`"). A
   cross-origin `fetch` with `credentials: "include"` needs an explicit,
   credentialed CORS policy naming the calling origin; same-origin
   deployments (the existing Vercel rewrite) do not. This phase adds no
   CORS configuration, since no frontend route consumes these endpoints
   yet — flagged as required before any browser-based login flow is
   wired up, not resolved here.

Login intentionally does not attempt to equalize response timing between
"unknown email" and "wrong password" (e.g., by hashing a dummy password on
a miss). This is a real, known mitigation for timing-based user
enumeration, and its omission is a genuine residual gap for this phase —
recorded explicitly in "Consequences" rather than silently accepted,
because CLAUDE.md's implementation discipline says not to add defensive
code beyond what a task asks for, and closing this gap was not part of the
requested scope.

## Decision

Implement Phase 1 only, as scoped above: a `users` table (`id`, `email`,
`password_hash`, `created_at`), Argon2id password hashing via
`argon2-cffi`, a signed/`httponly`/`secure`/`samesite=lax` session cookie
via `itsdangerous`, `POST /v1/auth/register`, `POST /v1/auth/login`,
`POST /v1/auth/logout`, and a `get_current_user` dependency that reads and
validates the cookie and loads the corresponding user row. None of
`get_github_connector`, `get_jira_connector`, `get_incident_source`, or any
existing route is modified. The following phases are named here so the
overall shape is visible, but neither designed nor implemented by this
ADR:

- **Phase 2 (future ADR):** per-user GitHub/Jira/Sentry credential
  storage — encryption-at-rest strategy, key management, and the schema
  for storing a user's own tokens.
- **Phase 3 (future ADR):** rewiring `get_github_connector`/
  `get_jira_connector`/`get_incident_source` from `app.state` singletons
  to per-request resolution keyed on `get_current_user`, plus deciding
  what an anonymous (unauthenticated) request does once authenticated
  mode exists alongside it.
- **Phase 4 (possible future ADR):** whether stored personal-access
  tokens are ever replaced with GitHub/Jira/Sentry OAuth app flows.

## Consequences

## Implementation update (2026-08-28)

**IMPLEMENTED: Phase 2 credential storage.** A new additive `credentials`
table holds one Fernet-encrypted GitHub, Jira, or Sentry token per user and
provider. `POST`/`GET`/`DELETE /v1/credentials` require the Phase 1 current
user dependency and expose connection status only. Fernet-key resolution is
lazy, on first credential use. Connector dependency factories remain
unchanged: stored credentials are not used to construct a connector until
Phase 3 is explicitly designed and implemented.

- New module `app/auth/token_cipher.py` validates
  `PROMPTQL_CREDENTIAL_ENCRYPTION_KEY` only at use time and maps malformed
  cryptographic inputs to sanitized application errors.
- New `CredentialRepository` and `PostgresCredentialRepository` own
  encryption-before-write, decryption-on-read, provider-only listing, and
  composite-key upsert behavior. Tokens and ciphertext are excluded from
  representations and HTTP responses.
- `GitHubSettings`, `JiraSettings`, and `SentrySettings` now provide pure
  `from_stored_credential()` constructors, but no connector factory calls
  them yet.

The original Phase 1 decision record remains otherwise unchanged below.

- New module `app/auth/` (domain model, errors, Argon2 hashing,
  `itsdangerous` session signing, the `UserRepository` protocol, and an
  `InMemoryUserRepository` test double), matching the existing
  domain/persistence split already used for runtime
  (`app/runtime/repository.py`'s `RunRepository`/`FactRecurrenceRepository`
  protocols against `app/database/postgres_run_repository.py`/
  `postgres_fact_recurrence_repository.py`).
- New `app/database/postgres_user_repository.py` and a `UserRow` model in
  `app/database/models.py`; Argon2 hashes never leave
  `PostgresUserRepository` — callers only ever receive the hash-free `User`
  domain model.
- New migration creating `users`, independent of every existing table (no
  foreign key in either direction).
- `verify_database_ready()` (`app/database/engine.py`) gains `users` in
  its required-table set, so a deployment that has not run this migration
  fails startup the same way a pre-ADR-004 or pre-ADR-031 deployment would,
  rather than serving auth routes against a table that does not exist.
- New `app/api/v1/auth_router.py`, included in `main.py` alongside the
  existing `connector_router`/`live_events_router`, and two new
  `ApiErrorCode` members (`USER_ALREADY_EXISTS`, `INVALID_CREDENTIALS`) on
  the existing `ApiError` shape in `app/api/v1/models.py`, reusing the
  established typed-error-response convention instead of inventing a new
  one.
- `AuthSettings` (new, in `app/config.py`) is resolved lazily, inside the
  `get_session_signer` dependency on first use, and cached on `app.state`
  after that — not eagerly at `create_app()` construction time, and not in
  `lifespan()` either. Unlike `DatabaseSettings`, which resolves inside
  `lifespan()` because standing up the engine and verifying it is real
  I/O that must complete before the application is "ready," building a
  `SessionSigner` from `AuthSettings` does no I/O at all, so there is no
  reason to force `AUTH_SESSION_SECRET_KEY`'s presence into the async
  startup path. This also means a missing `AUTH_SESSION_SECRET_KEY` fails
  the first request that actually needs it (as a sanitized 503
  `AuthPersistenceError`, the same shape used for a missing auth
  persistence session factory), not module *import* and not even
  application *startup* — which matters concretely: an existing test,
  `test_startup_logs_selected_github_and_jira_sources`
  (`tests/unit/test_application_startup_logging.py`), exercises
  `application.router.lifespan_context(application)` directly without
  issuing any HTTP request, so an eager lifespan-time resolution would
  have forced that pre-existing test to change to mock `AuthSettings` too.
  Lazy, request-time resolution avoids that entirely, keeping this ADR's
  zero-test-file-edit requirement for the pre-existing suite intact.
- The residual gaps named in "Reasoning review" — `secure=True` requiring
  local HTTPS to exercise via a browser, no CORS policy yet, and no
  login-timing equalization — are real and are not fixed by this ADR.
- Not materially relevant to this ADR: `MergeReadinessRun`/
  `InvestigationRun` persistence, the connector factory functions, the
  planner/hypothesis/code-diagnosis LLM boundary, and the frontend — none
  are touched.

## Invariants

- No existing table's columns, constraints, or semantics change.
- `get_github_connector`, `get_jira_connector`, `get_incident_source`, and
  every route defined before this ADR keep their exact current behavior;
  none read or depend on `get_current_user`.
- A password is never persisted or logged in cleartext; only
  `argon2-cffi`'s `PasswordHasher.hash()` output is stored.
- The session cookie value is opaque to the client and carries only
  `user_id`; it is signed and its signature and age are both verified on
  every read, and it is never accepted unsigned or expired.
- `users.email` uniqueness is enforced against the lowercased, trimmed
  form of the address, applied identically on every write and read path
  (registration, login, and any future lookup) — not just at the database
  constraint.
- `AUTH_SESSION_SECRET_KEY` is required and validated for minimum length
  before any session token is signed; the application does not fall back
  to an implicit or hardcoded secret.

## Validation

`uv run python -m unittest discover -s tests -v` from `services/api`, with
new coverage for: Argon2 hashing round trip (correct password accepted,
incorrect rejected, and hash output differs from the input), session
cookie signing/validation (valid token accepted, tampered signature
rejected, expired token rejected, unsigned/garbage input rejected), and
`register`/`login`/`logout` HTTP behavior (successful registration sets
the cookie and returns the user, duplicate email registration returns 409,
correct-credential login sets the cookie, incorrect-credential login
returns 401 without revealing whether the email exists, and logout clears
the cookie). The full existing suite is required to pass with zero
test-file changes, proving the anonymous demo path is unaffected.

## Reconsideration triggers

Revisit the stateless-cookie choice if a concrete requirement emerges for
server-side session revocation before expiry (e.g., an admin-initiated
"log out this user everywhere," or compromised-credential response) — that
needs a server-side session record this ADR deliberately avoids adding
now. Revisit `email_verified`/password-reset columns when a concrete
verification or reset flow is designed, rather than adding the columns
speculatively now. Revisit the login-timing gap if user enumeration is
ever demonstrated to matter for this deployment's actual threat model.
Revisit `secure=True`/CORS handling together, as one piece, when a
frontend login flow is actually built — not before, since neither can be
meaningfully validated without the other.
