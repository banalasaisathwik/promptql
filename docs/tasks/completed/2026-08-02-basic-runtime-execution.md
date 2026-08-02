# Task: Basic merge-readiness runtime execution

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-02
- Related ADRs: ADR-003
- Related execution plan: `docs/plans/completed/2026-08-02-basic-runtime-execution.md`

## Objective

Return typed operational run metadata around the existing deterministic
merge-readiness workflow.

## Current behavior

The readiness route had no run lifecycle or recorded execution steps.

## Scope

- Immutable run and step models, transition enforcement, repository protocol,
  synchronous workflow recording, HTTP `200`/`500` semantics, and tests.

## Non-goals

- Persistence, distributed work, queues, retries, cancellation APIs,
  authentication, dashboards, tracing, real connectors, or policy changes.

## Acceptance criteria

- [x] Completed runs contain a typed deterministic result.
- [x] Failed runs contain complete metadata, a sanitized error, and null result.
- [x] All executed steps contain IDs, status, timing, duration, and attempt one.
- [x] Terminal transitions are enforced.
- [x] The route delegates to the workflow service.

## Invariants

- A policy blocker is not a runtime failure.
- Unexpected exceptions never expose their original messages or traces.

## Failure cases

Unexpected connector and policy exceptions return typed HTTP `500` failed runs.
Validation still returns `422`; fixture lookup still returns structured `404`.

## Security

Only fixed sanitized runtime messages are public. This does not add identity,
authorization, or tenant boundaries.

## Observability

Run and step metadata are response-visible but not durable or traced.

## Validation

- 38 backend tests passed.
- Python compilation passed.
- 7 frontend tests, TypeScript/Vite build, and Oxlint passed.

## Completion notes

The storage protocol is ready for a separately designed persistence adapter.
The current request-local in-memory repository is intentionally temporary.
