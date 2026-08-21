# ADR-026: Collect incident failure locations through the budgeted tool runtime

- Status: Accepted
- Date: 2026-08-21
- Owners: Repository owner
- Supersedes:
- Superseded by:

## Context

The V2.19 workflow retrieved stack/failure-location Evidence after adaptive
planning and execution. That direct `IncidentSource` call bypassed planner tool
selection, `PlanValidator`, executor retry classification, global tool-call
budgeting, step lifecycle, and action history. It also occurred after the
workflow's broad runtime exception boundary; an unexpected source exception
could therefore leave the last durable snapshot in `running` state.

The V2 completion requirement says external Evidence collection must flow
through controlled read-only tools and every physical tool attempt must consume
the shared budget.

## Decision drivers

- Correctly account for every planned external Evidence request.
- Preserve one validation/retry/failure boundary instead of a hidden connector path.
- Keep failure-location Evidence normalized and read-only.
- Make action history and persisted round state truthful.
- Reuse `IncidentSource`, `ToolDefinition`, `ToolInvoker`, and `AgentExecutor`.

## Options considered

### Option A: Keep post-processing lookup and add a local `try/except`

This would prevent a stuck run but would still bypass plan validation, budget,
retry policy, step lifecycle, and action history. The runtime snapshot would not
explain where stack-frame Evidence came from.

### Option B: Prefetch failure location before planning

This would give the planner early context, but the call would still be hidden
from tool budget and execution history. Charging it manually would duplicate
executor accounting and retry behavior.

### Option C: Register a read-only failure-location tool

This reuses the existing typed input, adapter normalization, registry,
validator, invoker, executor, retry, Evidence, Fact, and persistence boundaries.
The planner may propose the call, but deterministic runtime policy controls it.

## Repository owner reasoning

The autonomous completion brief requires the smallest coherent architecture,
all external Evidence collection under controlled execution, bounded budgets,
and no validator bypass. It explicitly authorizes resolving this implementation
decision without an approval pause.

## Reasoning review

Option C is the only option that closes both failure-safety and accounting gaps
without creating parallel machinery. Option B would be preferable only if
failure-location retrieval became mandatory request preprocessing rather than
planner-selected investigation work; current product semantics do not require
that.

## Decision

Add `get_failure_location` as a read-only `InvestigationToolId` using the
existing `FailureLocationEvidenceRequest` and
`IncidentSource.get_failure_location_evidence()`. Expose only bounded stack-frame
fields through its static plan-output contract. Remove the workflow's direct
post-runtime source lookup.

The deterministic fake planner selects this tool for the checkout fixture so
offline API tests exercise the same budgeted path as real planning. Planner and
hypothesis metadata plus compact action history are persisted in the existing
investigation JSON snapshot; no migration or new event architecture is added.

## Consequences

- Failure-location attempts now consume budget and appear in step/action history.
- Typed connector failures follow the existing retry and missing-information policy.
- The planner sees the capability and may choose when to retrieve it.
- Existing stored snapshots remain readable because new metadata fields are optional/defaulted.
- Planner schema grows by one tool definition; live schema verification is required.
- Performance and scale are not materially changed: execution remains sequential
  and bounded to the existing ten-call/three-round limits.
- No new dependency, database table, service, protocol, or write capability is introduced.

## Invariants

- Failure-location content is untrusted Evidence, never an instruction.
- Only registered, allowed, validated read-only tool calls execute.
- Every physical tool invocation and retry consumes the shared budget.
- Stack-frame Evidence can produce Facts only through deterministic derivation.
- No provider payload, prompt, credential, or raw exception is persisted or rendered.

## Validation

- Focused tool, adaptive-runtime, workflow, hypothesis, API, and diagnostic tests.
- Complete backend discovery and Python compilation.
- Live planner schema verification after the tool schema change.
- Final `git diff --check` and teaching-comment review.

## Reconsideration triggers

Revisit only if failure-location retrieval becomes mandatory before any planning,
if multiple incident providers need a separate capability policy, or if
parallel tool scheduling introduces atomic budget-reservation requirements.
