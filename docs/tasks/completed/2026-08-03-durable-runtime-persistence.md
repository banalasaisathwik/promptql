# Task: Durable runtime persistence

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-03
- Related ADRs: ADR-003, ADR-004
- Related execution plan: `docs/plans/completed/2026-08-03-durable-runtime-persistence.md`

## Objective

Persist typed runtime runs and ordered steps in managed PostgreSQL, expose run
retrieval, and preserve existing completed/failed HTTP semantics.

## Scope

- SQLAlchemy and psycopg repository
- Alembic migration
- Safe environment configuration and pooling
- Atomic terminal checkpoints
- `GET /v1/runs/{run_id}`
- Credential-free and opt-in PostgreSQL tests

## Non-goals

- Neon resource creation, retries, workers, queues, cancellation, authentication,
  tracing, retention, dashboards, or real connectors

## Validation

- `uv run python -m unittest discover -s tests -v`: 54 discovered, 50 passed,
  four PostgreSQL tests skipped because `TEST_DATABASE_URL` was absent
- `uv run python -m compileall -q app tests migrations`: passed
- `uv run alembic heads`: one head, `20260803_0001`
- `uv run alembic upgrade head --sql` with a non-routable placeholder URL:
  rendered successfully without connecting to PostgreSQL

## Completion notes

No managed resource was created and no remote migration ran. PostgreSQL behavior
remains unverified until the guarded integration tests run against an approved
dedicated test branch.
