# Execution plan: Live workflow run dashboard

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-16
- Last updated: 2026-08-16
- Related ADRs: ADR-003, ADR-004, ADR-005, ADR-018
- Related tasks: None

## Objective

Add a developer-facing `/runs/:runId` dashboard that observes persisted V1
workflow snapshots while a newly accepted in-process run advances.

## Current behavior and evidence

`MergeReadinessWorkflowService.execute()` creates and persists its run before
moving it through runtime states, but
`POST /v1/pull-request-merge-readiness` awaits terminal completion before
returning its ID. `GET /v1/runs/{run_id}` already reads current persisted state.
The web transport/parser only recognizes terminal run bodies and the web app
currently renders one root page without client-side routes.

## Proposed behavior

```text
POST /v1/pull-request-merge-readiness-runs
-> persist pending snapshot
-> 202 {run_id, status: pending}
-> in-process workflow continuation

browser -> /runs/:runId -> validated GET snapshot -> render
                        -> one-second serialized polling while non-terminal
```

## Scope

- In scope: additive live-start API, bounded application task registry,
  persisted-snapshot dashboard, validated polling, navigation, tests, ADR,
  architecture/Mermaid/learning documentation.
- Expected systems and files: workflow, v1 router/models, application
  lifespan, frontend inspection transport/types/validation/page/components/CSS,
  backend and frontend tests, architecture/testing docs.

## Non-goals

- No SSE, WebSockets, `RunEvent`, queues, workers, retries, cancellation,
  replay, Grafana product queries, policy duplication, or V2 execution models.

## Acceptance criteria

- [x] Live-start returns a committed pending run ID before terminal completion.
- [x] GET exposes persisted pending/running/terminal snapshots safely.
- [x] The existing synchronous POST contract remains unchanged.
- [x] `/runs/:runId` renders header, current activity, ordered steps, result or
      sanitized failure, source provenance, and validated raw JSON.
- [x] Polling is serialized, abortable, terminal-aware, and separates refresh
      errors from workflow failures.
- [x] No provider call, queue, or event architecture is added.

## Invariants

- PostgreSQL snapshots are the dashboard source of truth.
- Only the backend policy provides `ready`, `blocked`, or `unknown`.
- Background execution is process-local, never described as durable work.
- Product visibility and operational OTel/Grafana remain separate.

## Failure cases and recovery

| Failure | Observable behavior | Recovery |
| --- | --- | --- |
| Initial persistence fails | Existing sanitized 503/409 response; no 202 | Restore database availability or schema |
| Connector/policy fails in task | Persisted typed failed run; dashboard shows sanitized error | Inspect run and operational telemetry |
| Dashboard refresh fails | Existing snapshot remains visible with separate refresh notice | Serialized poll retries while active |
| Process stops | Last committed snapshot remains readable; task does not resume | Restart process; durable workers are future work |

## Security

The browser receives only the existing typed run fields and sanitized runtime
errors after frontend validation. It never receives traces, credentials, raw
provider errors, or model reasoning.

## Observability

Reuse existing workflow/persistence telemetry. The dashboard does not create a
new telemetry pipeline or query Grafana.

## Validation strategy

Run focused API/workflow tests, frontend transport/dashboard tests, full backend
and frontend suites, lint/type/build, compile, and `git diff --check`.

## Progress

- [x] 2026-08-16: Inspected current runtime, API, frontend, tests, docs, and
      worktree. Confirmed synchronous POST cannot produce live observation.
- [x] Implemented the additive live-start endpoint, task registry, run route,
      validated polling, dashboard, documentation, and tests. Full backend
      discovery passed with the existing PostgreSQL credential-gated skips;
      frontend tests, lint, and build passed.

## Decisions and discoveries

- ADR-018 records the selected additive 202 endpoint and in-process task
  boundary. It is intentionally not durable execution.

## Risks and open questions

- This is appropriate for the local/developer workload only; a later durable
  worker and event stream must replace the task launcher when recovery or
  high-fan-out updates matter.

## Completion

Completed on 2026-08-16. Validation used the repository virtual environment
because the shared uv cache had an access-denied error. `python -m unittest
discover -s tests -v` ran 211 tests successfully with 6 explicit PostgreSQL
skips. Frontend `bun run test`, `bun run lint`, and `bun run build` passed with
29 tests. `compileall` and `git diff --check` passed. No live provider call,
database migration, queue, worker, SSE, or WebSocket was introduced.
