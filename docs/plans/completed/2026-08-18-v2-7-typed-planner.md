# Execution plan: V2.7 typed LLM planner

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-18
- Related milestone: V2.7

## Objective

Convert compact structured investigation state into a small typed proposal
through the existing provider-neutral LLM boundary, without executing it or
making generated content authoritative.

## Implemented direction

1. Add immutable contracts for bounded steps, literal arguments, and explicit
   step-output references.
2. Deterministically compress and order evidence, Facts, missing information,
   and the caller-supplied allowed-tool subset.
3. Add a versioned prompt and planner that distinguishes provider, malformed
   response, and plan-schema failures.
4. Extend existing LLM adapters with a typed request method while leaving V1
   explanation behavior unchanged.

## Invariants and non-goals

- Proposals never execute tools or create Facts/hypotheses.
- Tool gating remains caller-owned; no dynamic gating is added.
- `depends_on` is a control dependency and `StepOutputRef` is a data dependency,
  but V2.7 does not validate DAG semantics.
- V2.6 remains independent; V2.8 validation and V2.9 execution are deferred.

## Validation

Run focused planner and regression tests, backend discovery, compilation, diff
hygiene, then the required final teaching-comment pass and affected reruns.

## Completion

- `PlannerInput`, bounded `InvestigationPlan`, literal arguments, and explicit
  `StepOutputRef` contracts are implemented.
- The planner uses an injected provider-neutral typed client and only returns a
  schema-validated proposal with prompt/provider/model metadata.
- V2.8 graph/semantic validation and V2.9 execution remain absent by design.
- Focused tests, full backend discovery, compilation, and post-comment checks
  pass without live credentials.
