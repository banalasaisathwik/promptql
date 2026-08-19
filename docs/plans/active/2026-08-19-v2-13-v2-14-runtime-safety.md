# V2.13-V2.14 runtime safety boundaries

## Objective

Make the current read-only investigation runtime's retry assumption explicit
and define the process-local crash-recovery boundary without adding an
idempotency system, durable checkpointing, or resume execution.

## Starting behavior

- V2.5 `ToolDefinition.read_only` already marks every registered investigation
  tool as read-only.
- V2.12 retries only typed transient failures, up to three total attempts,
  while V2.10 consumes budget before every attempt.
- `AgentExecutor` produces only in-memory `InvestigationExecutionState`.
- V1 PostgreSQL persistence saves merge-readiness run/step snapshots, not V2
  execution state or a resumable agent.

## Scope and decisions

### V2.13 - implemented and verified boundary

- One logical `PlanStep` can have multiple attempts; attempt count never
  changes the step identity.
- Existing `read_only` metadata is the single current safety dimension. No
  duplicate `idempotent`, `retry_safe`, or similar flags are added.
- All seven current adapters were inspected and only retrieve normalized
  evidence from GitHub, incident, telemetry, or Jira boundaries.
- A future side-effecting tool is non-auto-retry by default until it owns an
  explicit idempotency or reconciliation contract.

### V2.14 - explicitly postponed durable recovery

- Current V2 execution is process-local and non-resumable after process loss.
- V1 PostgreSQL run/step persistence must not be presented as durable V2 agent
  execution.
- Future recovery should use checkpoint/snapshot state, not event sourcing by
  default, unless later requirements justify the additional event model.
- A prior `RUNNING` tool step is unknown after a crash; it cannot be silently
  converted to success or failure.

## Invariants and failure behavior

- Each actual provider call, including a retry, consumes one tool-call budget
  unit.
- Read-only retry safety does not imply fixed observations or exactly-once
  execution.
- A sent request whose response was not recorded is an in-flight ambiguity.
- Blind replay is prohibited for future side-effecting operations until
  idempotency or external reconciliation resolves that ambiguity.

## Non-goals

- Idempotency keys, deduplication storage, write/remediation tools, exactly-once
  claims, provider deduplication, or replay.
- Checkpoint tables/serialization/version migrations, resume APIs/workers,
  startup scans, crash simulation, event sourcing, leases, heartbeats, or
  multi-worker recovery.

## Validation

Run the focused V2.12 retry/budget tests and V1 persistence tests, then the
normal backend regression suite. PostgreSQL integration tests remain explicitly
environment-guarded when `TEST_DATABASE_URL` is absent.

## Progress

- [x] Inspected V2 tool metadata, all tool adapters, executor/retry policy,
  V1 persistence, architecture, ADR-023, ADR-004, and relevant tests.
- [x] Verified V2.13 needs documentation only; existing `read_only` metadata
  already establishes the required current-tool boundary.
- [x] Documented V2.14 as process-local/non-resumable and durable recovery as
  postponed.
- [x] Focused V2 retry/tool tests, V1 runtime-state and persistence tests,
  Python compilation, and full backend discovery completed; PostgreSQL tests
  were explicitly skipped because `TEST_DATABASE_URL` is absent.
- [x] Final documentation diff and local Mermaid learning diagram reviewed.
