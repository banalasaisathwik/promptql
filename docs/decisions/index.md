# Architecture decision records

ADRs preserve why durable choices were made. They complement the [current
architecture](../ARCHITECTURE.md): architecture says what exists now; ADRs
retain decision history and trade-offs.

## Statuses

- **Proposed:** under discussion; not authorization to implement.
- **Accepted:** approved and currently authoritative.
- **Superseded:** replaced by a newer ADR and retained as history.
- **Deprecated:** no longer recommended but not necessarily replaced.
- **Rejected:** considered and deliberately not selected.

Never rewrite an accepted historical ADR to make a later choice appear original.
Create a new ADR, mark the old one superseded, and link both.

## Register

| ADR | Status | Decision |
| --- | --- | --- |
| [ADR-001](ADR-001-versioned-connector-inspection-api.md) | Accepted | Versioned inspection endpoint, backend-owned demo fixture catalog, and relative `/v1` frontend routing |
| [ADR-002](ADR-002-merge-readiness-http-workflow.md) | Accepted | Additive merge-readiness endpoint with backend-owned policy decisions and supporting connector facts |
| [ADR-003](ADR-003-basic-runtime-execution.md) | Accepted | Synchronous runtime runs, recorded steps, replaceable storage, and typed HTTP 500 failed-run bodies |
| [ADR-004](ADR-004-durable-runtime-persistence.md) | Accepted | Neon PostgreSQL persistence through SQLAlchemy, Alembic migrations, short transactions, and run retrieval |
| [ADR-005](ADR-005-opentelemetry-observability.md) | Accepted | Provider-neutral OpenTelemetry traces and metrics, Grafana Cloud OTLP export, bounded telemetry, and post-commit terminal reporting |
| [ADR-006](ADR-006-read-only-github-rest-connector.md) | Accepted | Async read-only GitHub REST connector selected by configuration, normalized evidence, bounded pagination, and no fake fallback |
| [ADR-007](ADR-007-read-only-jira-cloud-connector.md) | Partially superseded by ADR-008 | Async read-only Jira Cloud REST connector, category-based status semantics, independent source selection, and honest unknown blocker normalization |
| [ADR-008](ADR-008-optional-jira-blocker-evidence.md) | Accepted | Treat unknown Jira blocker metadata as optional V1 evidence while explicit blockers remain blocking |
