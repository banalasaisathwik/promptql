# ADR-025: Investigation console reuses persisted run snapshots

- Status: Accepted
- Date: 2026-08-19
- Related: ADR-018, ADR-024

## Context

V2.17 and V2.18 provide typed hypothesis generation and deterministic Fact
validation, but they were not connected to the user-facing API. PromptQL
already exposes live workflow state through a committed pending run, an
in-process task, PostgreSQL snapshots, and serialized polling of
`GET /v1/runs/{run_id}`.

The investigation console needs planning/tool progress without creating a
second SSE, WebSocket, event bus, or client-side state reconstruction system.

## Decision

Add a typed `InvestigationRun` variant to the existing run resource. Store its
structured investigation state in a nullable `investigation_state` JSON column;
preserve existing V1 merge-readiness rows and their step table unchanged. The
investigation workflow uses the existing `LiveRunTaskRegistry` and repository
protocol, and the frontend uses the existing serialized snapshot poller.

The investigation state contains planning rounds, normalized Evidence,
derived Facts, missing information, validated hypotheses, bounded budget
accounting, and a semantic termination reason. Candidate hypotheses and raw
provider prose are not exposed.

## Alternatives

1. Create separate investigation tables and a second polling resource. This
   would isolate schemas but duplicate lifecycle and retrieval behavior.
2. Keep investigation state process-local. This would be simpler but would
   disappear on refresh and contradict the existing persisted live-state model.
3. Add a new streaming system. This was rejected because current snapshots
   already represent the required progress for the local/developer workload.

## Consequences

- V1 run behavior remains backward compatible.
- One resource can be refreshed or bookmarked for either workflow kind.
- Snapshot polling reports current truth, not an event history or replay log.
- Investigation progress is compact and typed, but high-fan-out streaming,
  crash recovery, and replay remain future work.
