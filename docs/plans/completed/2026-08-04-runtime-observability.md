# Execution plan: Provider-neutral runtime observability

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-04
- Last updated: 2026-08-04
- Related ADRs: ADR-005
- Related tasks: `docs/tasks/completed/2026-08-04-runtime-observability.md`

## Objective

Add a bounded observability foundation across FastAPI, synchronous workflow
execution, and runtime persistence without changing business semantics.

## Current behavior and evidence

FastAPI creates application-scoped providers, automatic HTTP spans, and a
runtime telemetry facade. Workflow and repository code add explicit domain
spans and post-commit measurements. In-memory tests verify this end to end.

## Proposed behavior

The completed flow is HTTP server span -> workflow span -> connector, policy,
and persistence spans -> durable terminal save -> terminal metric and JSON log.

## Scope

- In scope: traces, metrics, JSON logging, OTLP/configuration, lifecycle,
  decorator, safety boundaries, tests, and documentation.
- Expected systems and files: `services/api`, backend tests, and repository docs.

## Non-goals

- Not included: frontend observability, dashboards, alerts, OTel Collector,
  Docker, SQL tracing, logs export, worker tracing, or deployment setup.

## Acceptance criteria

- [x] Trace hierarchy, metrics, redaction, failure isolation, and durable
  terminal ordering are verified without external credentials.

## Invariants

- Observability is best effort and cannot become a business dependency.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Invalid telemetry settings | One sanitized warning; no-op OTel | Correct environment and restart |
| Exporter outage | Workflow remains unchanged; bounded warning | Export resumes after provider recovery/restart |
| Terminal database commit fails | Persistence failure only; existing `503` | Restore database, then retry request |

## Security

Telemetry uses closed attributes and failure categories. It never records raw
exceptions, connector/policy payloads, database values, SQL, headers, or bodies.

## Observability

This plan implements observability itself; ADR-005 is the durable source of
truth for span hierarchy, metrics, lifecycle, and provider trade-offs.

## Milestones

1. Add safe application-scoped OTel configuration and lifecycle.
2. Instrument workflow and persistence with post-commit terminal semantics.
3. Prove hierarchy, metrics, redaction, and isolation with in-memory tests.
4. Update operational, architecture, decision, and learning documentation.

## Validation strategy

Run focused observability tests, Python compilation, full backend discovery,
frontend regression tests, TypeScript/Vite build, Oxlint, and diff checks.

## Progress

- [x] 2026-08-04: Dependencies and safe setup added.
- [x] 2026-08-04: Runtime and repository instrumentation completed.
- [x] 2026-08-04: Credential-free verification completed.
- [x] 2026-08-04: Documentation synchronized with verified behavior.

## Decisions and discoveries

The OTel exporter may log raw network details internally, so its internal
loggers are isolated and exporter failures cross a sanitized wrapper. FastAPI
instrumentation receives explicit providers so app factories remain testable.

## Risks and open questions

- In-process batch queues can lose recent telemetry on abrupt termination.
- Grafana dashboards, alert thresholds, and production collector topology are
  deferred until real deployment traffic exists.

## Completion

All credential-free checks passed. Four guarded PostgreSQL tests skipped
because `TEST_DATABASE_URL` was not configured. No remote service was changed.
