# Execution plan: V2.8 deterministic plan validator

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-18
- Related ADRs: ADR-022

## Objective

Reject statically illegal typed LLM plans before any V2.9 execution path exists.

## Current behavior and evidence

V2.7 parses bounded `InvestigationPlan` proposals but does not validate their
tool permissions, DAG structure, references, or types.

## Proposed behavior

`PlanValidator` receives a plan, a metadata-only registry, and caller-injected
allowed tools. It returns one `ValidatedPlan` with deterministic topological
order, or typed sanitized failures with no partial plan.

## Non-goals

- Tool execution, scheduling, replanning, repair, quality scoring, budgets, and
  nested selector languages.

## Acceptance criteria

- [x] Focused tests, regression suite, compile, and final diff review pass.
- [x] Documentation records V2.8 as implemented.

## Invariants

- Planner visibility is guidance; the validator enforces the allowlist.
- Static output contracts never change V2.5 runtime tool behavior.
- Invalid plans are rejected atomically.

## Completion

Focused validator/planner/registry tests and complete backend discovery passed.
No tool adapter, runtime, API, or provider call was added.
