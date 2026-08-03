# Execution plan: Durable runtime persistence

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-03
- Last updated: 2026-08-03
- Related ADRs: ADR-003, ADR-004
- Related tasks: `docs/tasks/completed/2026-08-03-durable-runtime-persistence.md`

## Objective

Replace request-local production memory with durable PostgreSQL checkpoints
while retaining the simple repository and deterministic workflow boundaries.

## Implemented behavior

```text
validated request
→ pending and running rows commit
→ each step start commits
→ external work runs without a transaction
→ each step outcome and facts commit
→ policy step and terminal run commit atomically
→ POST response
→ later GET reconstructs the Pydantic run
```

## Failure behavior

| Failure | Observable behavior |
| --- | --- |
| Missing or invalid runtime URL | Application startup fails closed |
| Database unavailable during a request | Sanitized HTTP 503 |
| Connector or policy exception and failed commit succeeds | Typed HTTP 500 failed run |
| Terminal commit cannot be confirmed | HTTP 503; no HTTP 200/500 durable claim |
| Unknown run ID | Typed HTTP 404 |
| Stored JSON violates Pydantic contract | Sanitized HTTP 500 |

## Security

TLS is required in parsed URLs. Credentials stay in environment variables.
SQLAlchemy hides query parameters, and HTTP handlers use fixed messages rather
than database or exception text. PostgreSQL tests require an isolated-branch
confirmation and reject the configured application database.

## Completion

Credential-free code, API, safety, lifecycle, migration-rendering, and
compilation checks passed. Four PostgreSQL tests skipped because no authorized
`TEST_DATABASE_URL` was supplied. No database connection was attempted.
