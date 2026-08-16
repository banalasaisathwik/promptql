# ADR-018: Live run dashboard through persisted snapshot polling

- Status: Accepted
- Date: 2026-08-16
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

The V1 workflow already persists a pending run, running state, ordered step
snapshots, and a terminal result or sanitized failure. `GET /v1/runs/{run_id}`
returns that current persisted snapshot. The existing
`POST /v1/pull-request-merge-readiness` waits for terminal completion, so its
run ID arrives too late for a browser to observe that same execution live.

The dashboard needs live visibility for local/developer use without changing
the existing completion-oriented API contract or inventing a durable event
architecture before V2 needs it.

## Decision drivers

- Preserve V1 clients and the existing synchronous POST response contract.
- Make only committed runtime snapshots visible to the browser.
- Keep workflow, policy, persistence, and OpenTelemetry ownership unchanged.
- Avoid queue infrastructure, durable worker claims, SSE, WebSockets, and
  event storage in this milestone.
- Keep the frontend polling boundary replaceable by a future event stream.

## Options considered

### Additive in-process live-start endpoint

Persist a pending run, return `202 Accepted` with its ID, and run the existing
workflow in an application-lifetime in-process task. The browser polls the
existing GET route for snapshots. This preserves the existing POST and gives a
real run ID before terminal completion. A process crash can interrupt work,
but snapshots committed before that point remain readable.

### Change the existing synchronous POST to return 202

This would make the primary route live, but breaks clients that depend on its
completed/failed response body and its status semantics.

### Dashboard only, without a new start endpoint

This supports manually viewing historic runs but cannot observe a run started
from the existing page because the run ID is returned only after completion.

## Repository owner reasoning

The requested milestone explicitly prefers an additive `202` start flow while
retaining the existing synchronous V1 contract and avoiding worker/queue
infrastructure.

## Reasoning review

That choice correctly separates the durable state already owned by PostgreSQL
from the temporary process that advances it. An in-process task is sufficient
for local developer visibility but is not durable execution. A durable worker
and event stream become appropriate only when crash recovery, multi-process
execution, replay, or lower-latency fan-out are actual requirements.

## Decision

- Keep `POST /v1/pull-request-merge-readiness` unchanged.
- Add `POST /v1/pull-request-merge-readiness-runs`, which persists a pending
  snapshot and returns `202 Accepted` with `{run_id, status}`.
- Track the in-process continuation task only for its application lifetime;
  cancel pending tasks during shutdown.
- Have the dashboard poll `GET /v1/runs/{run_id}` about once a second while
  the snapshot is pending or running. It stops on a terminal snapshot,
  unmount, route change, or abort.
- Validate every fetched snapshot before rendering it. The dashboard consumes
  state, not events.

## Consequences

- Existing callers keep their synchronous contract unchanged.
- The new endpoint has explicit acceptance semantics: a pending snapshot was
  committed, not that work completed.
- Task memory is process-local and cannot recover a task after a restart;
  PostgreSQL remains the source of truth for already committed snapshots.
- Polling adds roughly one read per active dashboard per second. This is
  suitable for the small developer/demo workload, not a high-fan-out live UI.
- V2 can add durable `RunEvent` records and an SSE endpoint without changing
  the dashboard's rendering model: state answers what is true now, while an
  event answers what happened.

## Invariants

- Only persisted, frontend-validated snapshots reach the dashboard.
- The frontend never derives a merge-readiness decision.
- Runtime failures remain sanitized typed run state; dashboard refresh failures
  remain a separate browser concern.
- Grafana/OTel stays operational telemetry and is never queried by the product
  dashboard.

## Validation

Targeted backend API/workflow tests prove pending visibility before completion,
typed background failure, unchanged synchronous behavior, and safe 404s.
Frontend tests prove validated polling, terminal/unmount stops, no overlapping
requests, refresh-error separation, dashboard rendering, and live navigation.

## Reconsideration triggers

Revisit this decision when a process restart must resume work, many clients
need sub-second updates, execution moves outside one API process, or users need
history/replay rather than the latest state.
