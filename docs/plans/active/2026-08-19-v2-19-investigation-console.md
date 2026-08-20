# Execution plan: V2.19 grounded investigation console

- Status: Implemented offline; live provider/database verification remains external
- Owner: Repository owner
- Created: 2026-08-19
- Related ADRs: ADR-018, ADR-024, ADR-025

## Objective

Connect structured V2 investigation input to the existing persisted run snapshot
mechanism, expose execution state in a readable console, and render the final
result only from validated hypotheses and validated Facts.

## Decision and current behavior

`CandidateHypothesis` remains untrusted provider output. The deterministic
validator produces `ValidatedHypothesis`; `render_grounded_result()` accepts
only that type and resolves every supporting Fact ID before producing fixed
wording. The API adds `POST /v1/investigations` and extends `GET /v1/runs/{id}`
with an `InvestigationRun` variant. Existing V1 merge-readiness responses keep
their previous shape.

The frontend uses the same accepted-run ID, task registry, persisted snapshot,
and serialized polling path. It presents rounds, step status/attempts,
Evidence, Facts, missing information, validated hypotheses, budget, and the
grounded result as separate regions.

## Invariants

- Raw model causal prose never reaches the final result or normal UI.
- Every rendered supporting Fact ID must exist in the validated Fact set.
- Missing information and budget/provider termination remain visible and
  semantically distinct from runtime failure.
- The frontend displays backend state; it does not derive Facts or validate
  hypotheses.
- V1 run persistence, API shape, and dashboard behavior remain compatible.

## Validation

- Backend focused renderer/workflow/API tests use deterministic fake sources.
- Backend unit discovery must pass without provider credentials.
- Frontend tests, lint, and production build must pass.
- PostgreSQL migration and live provider checks remain environment-gated.

## Deliberately deferred

Langfuse, new streaming infrastructure, raw event replay, crash recovery,
LLM final rewriting, dependency hypothesis taxonomy, formal agent evals, and
live provider smoke tests.
