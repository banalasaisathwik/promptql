# ADR-004: Durable PostgreSQL runtime persistence

- Status: Accepted
- Date: 2026-08-03
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

ADR-003 introduced immutable run snapshots and a `RunRepository` boundary, but
the HTTP route created a request-local in-memory repository. Runs disappeared
after the request and could not be retrieved by ID. The owner approved managed
PostgreSQL persistence without Docker, background workers, retries, or provider
SDK coupling.

## Decision drivers

- Preserve the existing typed runtime and deterministic policy result
- Never return a successful terminal response before its commit succeeds
- Keep database transactions away from connector and policy execution
- Preserve crash-visible running steps
- Reject terminal or concurrent state replacement
- Avoid exposing credentials, SQL, driver errors, or exception text
- Keep unit tests fast and independent of database credentials

## Options considered

### Neon PostgreSQL through SQLAlchemy

Use Neon only as the managed PostgreSQL host. SQLAlchemy and psycopg provide the
application boundary; Alembic owns migrations. This supplies pooled runtime
connections, direct migration connections, and isolated test branches without
coupling domain code to a provider SDK.

### Supabase PostgreSQL through SQLAlchemy

This remains portable and would be preferable if PromptQL also adopted
Supabase Auth, Storage, Realtime, or browser-facing RLS. Those capabilities are
outside the current slice, so its broader platform and connection modes add no
present value.

### Self-managed or Docker PostgreSQL

This provides local control but violates the managed-only constraint and adds
operations unrelated to the persistence contract.

## Decision

- Use Neon as the managed PostgreSQL provider.
- Use synchronous SQLAlchemy 2.x with psycopg 3 because the workflow and
  connectors are synchronous.
- Use a pooled TLS `DATABASE_URL` for application traffic and an explicit direct
  TLS `DATABASE_MIGRATION_URL` for Alembic.
- Keep one engine per API process with a small SQLAlchemy pool and short
  session-per-repository-operation transactions.
- Store run and step identity, lifecycle, timestamps, version, attempt, and
  sequence number in relational columns with database checks.
- Store request, connector facts, result, and sanitized errors as JSONB typed
  snapshots; revalidate them with Pydantic on retrieval.
- Keep `RunRepository.save/get`. One save persists a complete snapshot in one
  transaction.
- Persist running steps before external work for crash visibility.
- Atomically persist terminal step and terminal run state.
- Use conditional status updates and affected-row checks. Do not add a version
  column until multiple workers can intentionally update one run.
- Add `GET /v1/runs/{run_id}` and return ordered steps.
- Use `InMemoryRunRepository` only through explicit test construction or
  dependency overrides.
- Fail application startup when configuration, connectivity, or migrations are
  missing. Never run migrations or create tables automatically.
- Return sanitized `503` when persistence is unavailable or durability cannot
  be confirmed.

## Consequences

- Correctness: completed and failed HTTP responses correspond to committed
  terminal rows, and terminal step/run state cannot split across commits.
- Failure behavior: earlier checkpoints survive later failures. A commit failure
  returns `503` instead of fabricating a durable terminal run.
- Security: URLs remain in environment variables, engine parameter logging is
  hidden, and HTTP handlers use fixed messages rather than exception text.
- Performance: each workflow writes several small checkpoints. The pool permits
  at most ten connections per process, so process count must be included in
  capacity planning.
- Testability: unit tests retain memory; PostgreSQL tests require an explicitly
  confirmed, isolated URL and otherwise skip clearly.
- Portability: JSONB and PostgreSQL checks intentionally target PostgreSQL, but
  no Neon SDK appears in application code.
- Trade-off: JSONB avoids a large provider-fact schema, but PostgreSQL cannot
  enforce the complete nested Pydantic structure.
- Trade-off: no version column keeps V1 simple, but same-status multi-writer
  updates will require optimistic versioning when workers or resume appear.

## Invariants

- No transaction or connection is held while calling a connector or policy.
- `HTTP 200` requires a committed completed run and non-null result.
- `HTTP 500` runtime failure requires a committed failed run and null result.
- Persistence uncertainty returns `HTTP 503` with no uncommitted run claim.
- Completed, failed, and cancelled rows cannot transition back to running.
- Step order is `UNIQUE(run_id, sequence_number)` and retrieval always orders by
  sequence number.
- Production never silently chooses in-memory persistence.

## Reconsideration triggers

- Multiple processes intentionally update or resume one run.
- Run cancellation or retries race with execution.
- Listing/filtering requires additional relational or JSONB indexes.
- Authentication and tenant ownership become available for run retrieval.
