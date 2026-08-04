# Task: Runtime tracing and metrics

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-04
- Related ADRs: ADR-005
- Related execution plan: `docs/plans/completed/2026-08-04-runtime-observability.md`

## Objective

Make HTTP, workflow, step, and runtime persistence behavior visible through
bounded OpenTelemetry traces and metrics plus correlated safe JSON events.

## Current behavior

The FastAPI application now owns one optional OTel setup. The readiness route,
workflow service, and observed repository produce one correlated trace without
changing the typed policy or persistence result.

## Scope

- In scope: OTel setup, OTLP HTTP/protobuf and opt-in console exporters, manual
  runtime spans and metrics, repository decoration, redaction, tests, and docs.
- Expected files: backend observability, workflow and API assembly, Python
  dependencies, backend tests, configuration examples, architecture, ADR, and
  learning documentation.

## Non-goals

- Not included: dashboards, alerts, collector deployment, OTel log export,
  SQLAlchemy instrumentation, retries, queues, workers, or real provider setup.

## Acceptance criteria

- [x] HTTP, domain, and persistence spans share a trace with correct parents.
- [x] Terminal metrics and events describe only committed terminal runs.
- [x] Business outcomes remain successful; system failures are sanitized.
- [x] Metric labels are exactly allowlisted and exporter failure is isolated.

## Invariants

- Telemetry never changes workflow, policy, persistence, or HTTP behavior.
- A terminal run measurement is emitted exactly once and only after commit.
- Raw exceptions, secrets, SQL, input values, headers, and payloads are absent.

## Failure cases

Invalid setup disables OTel with a bounded warning. Export failure remains
background best effort. Terminal persistence failure emits persistence failure
telemetry but no false completed/failed run metric.

## Security

Closed span/log attributes and exact metric label sets exclude unbounded or
sensitive values. Automatic exception and header/body capture are disabled.

## Observability

Five instruments, a stable domain span hierarchy, and four JSON event names are
implemented. Grafana Cloud is an environment-configured OTLP destination only.

## Validation

- Exact command: `uv run python -m compileall -q app tests`
- Exact command: `uv run python -m unittest discover -s tests -v`
- Exact commands: `bun run test:web`, `bun run build:web`, `bun run lint:web`
- Result: compilation passed; 68 backend tests ran with 64 passing and four
  PostgreSQL tests skipped without `TEST_DATABASE_URL`; seven frontend tests,
  the TypeScript/Vite build, and Oxlint passed.

## Completion notes

No Grafana or PostgreSQL resource was contacted or configured. The repository
has no configured backend formatter, linter, or static type-check command.
