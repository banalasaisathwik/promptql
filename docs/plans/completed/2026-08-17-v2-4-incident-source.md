# Execution plan: V2.4 IncidentSource and operational evidence

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-17
- Last updated: 2026-08-17
- Related ADRs: ADR-020, ADR-021

## Objective

Add a provider-neutral read-only boundary that produces normalized incident,
deployment, failure-location, and minimal telemetry-window evidence without
coupling the investigation domain to Grafana, Sentry, Datadog, or a query
language.

## Current behavior

V2.2 defines the immutable evidence envelope and V2.3 populates GitHub code
evidence. Existing Grafana Cloud integration exports application OpenTelemetry
data through OTLP; it does not configure a Grafana read/query client.

## Implemented scope

- `IncidentSource` protocol with four semantic evidence operations.
- Immutable request/content models with timezone-aware telemetry windows.
- Deterministic `FakeIncidentSource` fixtures for offline tests and learning.
- Explicit fixture lookup failure rather than fabricated empty evidence.
- No live provider adapter, new credentials, query-language input, runtime,
  planner, fact derivation, persistence, API, or frontend work.

## Invariants

- Every output is a V2.2 `Evidence` envelope with source/kind/content agreement.
- Timestamps are timezone-aware; event time and retrieval time remain distinct.
- A telemetry window has an ordered start/end and bounded structured filters.
- Raw provider payloads, raw stacks, PromQL, LogQL, and credentials never become
  domain data.
- Unavailable fixture data raises a typed lookup failure instead of becoming an
  empty observation.

## Validation strategy

1. Focused V2.4, evidence, investigation, and V2.3 regression tests.
2. Complete backend unittest discovery and Python compilation.
3. Teaching-comment pass on changed Python source, then rerun affected checks.
4. Diff hygiene, scope audit, and documentation/learning-flow review.

## Completion

- Focused V2.4/V2.1/V2.2/V2.3 tests: 72 passed.
- Complete backend discovery: 283 passed; 6 PostgreSQL tests skipped because
  `TEST_DATABASE_URL` is absent.
- `python -m compileall -q app tests` and `git diff --check` passed.
- The final code-teaching pass annotated the changed application source files;
  focused tests were rerun afterward with no executable changes from that pass.
- No live provider call, configuration, credential, API route, frontend change,
  planner tool, fact derivation, hypothesis logic, or persistence was added.

## Deferred

- Live Grafana/Sentry/Datadog adapters and provider query languages.
- Fact derivation, planner tools/registry, orchestration, persistence, API/UI,
  retries, budgets, and hypothesis generation.
