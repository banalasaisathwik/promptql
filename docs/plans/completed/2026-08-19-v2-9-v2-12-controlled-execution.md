# Execution plan: V2.9-V2.12 controlled investigation execution

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-19
- Related milestone: V2.9, V2.10, V2.11, V2.12

## Objective

Execute an already validated investigation DAG sequentially through the V2.5
tool surface, preserve partial evidence and derived facts, then place a small
deterministic total tool-call limit immediately before each attempted call.

## Current behavior and evidence

`PlanValidator` returns a `ValidatedPlan` with deterministic topological IDs in
`services/api/app/investigations/planning/validation.py`. V2.6 `ToolInvoker`
dispatches registered adapters and returns normalized `ToolResult` values in
`services/api/app/investigations/baseline.py`. `derive_facts` recomputes and
deduplicates deterministic facts from an evidence tuple.

## Proposed behavior

`AgentExecutor` interprets only `ValidatedPlan`: it resolves prior successful
step outputs from normalized evidence, validates the destination input model,
invokes the existing dispatcher, and records terminal step state. Each genuine
evidence addition recomputes Facts over all accumulated Evidence. A failed
parent blocks its descendants while unrelated steps continue. V2.10 adds a
sequential counter that reserves a call before invocation; exhaustion blocks
the remaining pending work and preserves partial state.

## Scope

- In scope: sequential dependency-aware execution, normalized runtime output
  projection, typed states/failures, evidence/fact accumulation, fixed budget,
  documentation, and tests.
- Expected systems and files: investigation execution module and exports,
  execution tests, architecture/roadmap/learning documentation, local Mermaid.

## Non-goals

- No planner call, dynamic replanning, jitter, parallel scheduler, persistence,
  checkpoint/resume, cancellation, hypotheses, provider changes, or LLM calls.

## Acceptance criteria

- [x] A valid chain and branch execute in deterministic dependency order.
- [x] Runtime references become typed tool inputs only after a successful source.
- [x] Failures block dependent descendants but preserve independent partial work.
- [x] Evidence and full-set fact derivation remain deduplicated.
- [x] Budget prevents calls beyond its limit and records typed policy termination.
- [x] Connector failure kind determines whether retry is permitted.
- [x] Retryable failures make at most three total calls with one-second then
      two-second exponential delays, and every call consumes V2.10 budget.

## Invariants

- Planner proposes, validator checks static legality, executor interprets only
  the accepted plan.
- Registry metadata remains metadata; `ToolInvoker` remains the dispatch point.
- Failed or blocked work never fabricates Evidence or Facts.
- A failed attempted call consumes budget; a never-invoked blocked step does not.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Tool result is failed | Step is `failed`; dependent work is blocked | Preserve partial state; future retry policy is deferred |
| Runtime output unavailable | Consumer is blocked without invoking its tool | Inspect normalized evidence/provider capability |
| Budget exhausted | Pending work is blocked; typed termination is set | Increase a future caller-selected limit and re-execute |

## Security

Only the V2.8-approved tool/argument graph executes. Runtime references read
normalized domain evidence, not raw provider payloads. No external text is sent
to an LLM and no write capability is introduced.

## Observability

This bounded in-process milestone exposes typed execution state, failures, and
termination. Full agent telemetry is explicitly deferred to V2.21.

## Milestones

1. V2.9: execution, reference resolution, partial failure, and full-set fact
   recomputation pass focused tests with no budget logic.
2. V2.10: budget accounting and exhaustion pass focused tests while V2.9 stays
   green.

## Validation strategy

Run focused execution tests, prior plan/baseline tests, full backend discovery,
Python compilation, `git diff --check`, then repeat focused validation after
the required teaching-comment pass.

## Progress

- [x] 2026-08-19: Verified clean committed V2.8 baseline `3e07c65` and created
  `feat/v2-9-v2-10-agent-execution`.
- [x] 2026-08-19: Implemented V2.9 and passed focused execution tests before
  adding budget behavior.
- [x] 2026-08-19: Implemented V2.10 and passed focused budget tests.
- [x] 2026-08-19: Owner confirmed V2.11-V2.12 policy: retry rate limits,
      timeouts, and upstream unavailability only; at most three total attempts;
      one-second then two-second delays; charge every attempt to V2.10 budget.
- [x] 2026-08-19: Implemented typed tool failures and executor retries; focused
      execution and tool-registry tests passed before the final comment pass.

## Decisions and discoveries

- Full recomputation is selected because existing deterministic rules can relate
  old and newly collected evidence; bounded V2 plan sizes make an incremental
  inference engine unnecessary.
- Sequential execution makes budget reservation a local counter. Concurrent
  execution would require atomic reservation and is postponed.

## Risks and open questions

- Runtime output projection requires a normalized evidence record carrying the
  promised field. Absence is represented as blocked dependent work, not guessed
  from provider data.

## Completion

2026-08-19: Focused execution and tool-registry tests passed before and after
the final `code-teacher-comments` pass. `python -m compileall -q app tests`,
`git -c filter.comment-strip.clean=cat diff --check`, and complete backend
discovery passed (329 tests, 6 explicit PostgreSQL skips). The final comment
pass changed only comments in implementation/test source. Jitter, deadlines,
retry-after handling, durable retry history, retry telemetry, concurrency,
and write-tool idempotency remain deferred.
