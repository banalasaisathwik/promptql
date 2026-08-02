# ADR-003: Basic synchronous runtime execution

- Status: Accepted
- Date: 2026-08-02
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

ADR-002 exposes deterministic merge readiness, but the route delegates to an
application function that retrieves facts and evaluates policy without a run
identity, lifecycle, step history, timing, or system-failure result. The next V1
slice needs operational execution metadata without selecting PostgreSQL,
workers, queues, retries, or tracing.

## Decision drivers

- Distinguish a valid `blocked` decision from a failed execution
- Preserve the pure policy and connector boundaries
- Enforce terminal run and step states
- Return safe diagnostics without exception text or stack traces
- Permit later persistence without coupling to PostgreSQL now
- Preserve the existing synchronous endpoint and frontend decision behavior

## Options considered

### Option A: Return HTTP 200 for completed and failed runs

The request successfully creates a run resource regardless of its terminal
state. Clients must always inspect `status`, but a synchronous execution failure
appears as an HTTP success and can be missed by ordinary monitoring.

### Option B: Return HTTP 500 with the complete failed-run body

Completed runs return `200`. Unexpected connector or policy execution failures
return `500` with the same typed run schema, `status=failed`, recorded steps, a
sanitized error, and `result=null`. This preserves HTTP failure semantics and
runtime evidence at the cost of documenting the model for two status codes.

### Option C: Return an ordinary HTTP 500 error body

This is conventional but discards the run ID, timestamps, and step history the
runtime exists to provide.

## Repository owner reasoning

The owner selected Option B and explicitly required the full typed failed run,
sanitized error, null result, and no stack trace or secret exposure.

## Reasoning review

Option B fits synchronous execution: the requested work did not complete, so
HTTP failure is truthful, while the response still preserves operational
evidence. Option A would fit an asynchronous run-submission API where creating
the run itself is the successful operation. Option C does not meet the task.

## Decision

- Add immutable typed runtime run, step, status, timing, and error models.
- Permit only explicit pending/running/terminal state transitions.
- Execute `fetch_github_facts`, `fetch_jira_facts`, then
  `evaluate_merge_readiness`, recording attempt one for each step.
- Treat expected connector unavailability as completed missing evidence.
- Treat policy `blocked`, `ready`, and `unknown` as completed execution.
- Convert unexpected connector or policy exceptions into sanitized failed runs.
- Return completed runs with HTTP `200` and failed runs with HTTP `500`.
- Introduce `RunRepository`; use request-local `InMemoryRunRepository` for V1.

## Consequences

- Correctness: terminal runs cannot return to running, and policy decisions are
  separate from execution status.
- Failure behavior: failed runs preserve completed/failed steps and omit the
  policy result; exception details never enter the public model.
- Complexity: immutable transition functions and workflow recording add code to
  the previously direct synchronous call.
- Testability: connector, policy, clock, and repository boundaries can be
  replaced without a database or network.
- Observability: run IDs, timestamps, durations, step order, and safe errors are
  available, but logs, metrics, traces, and durable history are absent.
- Performance: recording in-memory immutable snapshots adds negligible work for
  three local fixture steps. Real connector latency would dominate later.
- Scalability and operations: not materially relevant until durable concurrent
  execution or cross-process retrieval is required.
- Reversibility: no persisted schema or external service must be migrated.

## Invariants

- Routes and runtime code contain no merge-readiness rules.
- Identical facts produce identical policy results despite different run IDs
  and timestamps.
- Completed runs have a non-null result and no runtime error.
- Failed runs have a null result and a sanitized runtime error.
- Completed, failed, and cancelled states are terminal.
- Invalid input returns `422` before workflow execution normally begins.

## Validation

- 38 backend tests through `unittest` discovery
- Python compilation
- 7 frontend Bun tests, TypeScript/Vite build, and Oxlint

## Reconsideration triggers

- Runs must survive requests or process restarts.
- Work becomes asynchronous or distributed.
- Retry, cancellation, or idempotency semantics are required.
- Operational monitoring requires logs, metrics, or traces.
