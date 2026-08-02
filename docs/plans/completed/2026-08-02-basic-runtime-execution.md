# Execution plan: Basic runtime execution

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-02
- Last updated: 2026-08-02
- Related ADRs: ADR-003
- Related tasks: `docs/tasks/completed/2026-08-02-basic-runtime-execution.md`

## Objective

Execute the existing merge-readiness workflow as a typed run with recorded
connector and policy steps while keeping the workflow synchronous and local.

## Current behavior and evidence

The readiness route retrieved connector facts and evaluated policy directly.
Its result had no run ID, lifecycle, step records, timings, or structured system
failure.

## Proposed behavior

```text
HTTP request -> create run -> GitHub step -> Jira step -> policy step
             -> completed 200 or failed 500 typed run
```

## Scope

- Runtime models and transitions, repository protocol, in-memory adapter,
  workflow service, route delegation, typed response, and tests.

## Non-goals

- PostgreSQL, queues, workers, retries, cancellation endpoints, authentication,
  dashboards, OpenTelemetry, LLM planning, or real connectors.

## Acceptance criteria

- [x] Ready, blocked, and unknown policy results complete the runtime run.
- [x] Unexpected connector and policy exceptions fail the correct step and run.
- [x] Every run has a unique ID and steps retain execution order.
- [x] Terminal states cannot return to running.
- [x] The route delegates and declares both success and failed-run schemas.
- [x] Invalid input returns `422` without executing the workflow.

## Invariants

- Policy result determinism is independent from operational metadata.
- Failed responses contain no exception text or stack trace.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Failed CI | Completed run with `decision=blocked` | Fix CI and execute again |
| Expected connector unavailability | Completed run, usually `unknown` | Restore evidence and execute again |
| Unexpected connector exception | Failed step and run, HTTP `500` | Correct system failure and retry manually |
| Policy exception | Failed policy step and run, HTTP `500` | Correct policy implementation and retry manually |
| Invalid input | HTTP `422`, no run | Correct the request |

## Security

Runtime errors use fixed public messages. Raw exceptions and stack traces are
not serialized. Authentication and tenant isolation remain separate work.

## Observability

The response exposes run and step timing plus errors. Durable history, logs,
metrics, and traces are not implemented.

## Milestones

1. Runtime contracts, transitions, and storage boundary.
2. Recorded workflow, route delegation, compatibility, and tests.

## Validation strategy

- `uv run python -m unittest discover -s tests -v`
- `uv run python -m compileall -q app tests`
- `bun run test:web`
- `bun run build:web`
- `bun run lint:web`

## Progress

- [x] 2026-08-02: Runtime and workflow tests passed.
- [x] 2026-08-02: Complete backend and configured frontend checks passed.

## Decisions and discoveries

ADR-003 records the selected typed HTTP `500` failure contract. Successful
frontend responses now validate runtime metadata and read the policy from
`result`.

## Risks and open questions

- Request-local storage deliberately provides no retrieval or durability.

## Completion

All validation commands passed. The existing Starlette `TestClient` warning
remains. No dependency, persistent storage, worker, or retry path was added.
