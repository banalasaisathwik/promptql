# Task: Deterministic V1 merge-readiness policy

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-02
- Related ADRs: None
- Related execution plan: None; this was one bounded backend domain patch

## Objective

Convert existing typed GitHub and Jira facts into a deterministic, typed
merge-readiness result without performing I/O.

## Current behavior

Before this task, fake connectors returned validated provider facts and the
inspection service combined them. No module interpreted those facts as a
readiness decision.

## Scope

- In scope: typed policy outputs, direct deterministic evaluation, all ten V1
  blockers, blocked/unknown/ready precedence, evidence references, and unit
  tests.
- Expected files: `services/api/app/policy`, its unit test, and documentation
  describing the implemented boundary.

## Non-goals

- API or inspection-service integration
- LLM explanations
- Database persistence
- Real connectors or OAuth
- Runtime tracing
- Frontend behavior
- Configurable approval thresholds

## Acceptance criteria

- [x] Given the merge-ready fixtures, evaluation returns `ready`.
- [x] Given any requested verified blocker, evaluation returns `blocked` and
  cites its source evidence.
- [x] Given several blockers, every blocker is retained in stable order.
- [x] Given unavailable or indeterminate required evidence without a blocker,
  evaluation returns `unknown`.
- [x] Given both a verified blocker and missing information, `blocked` takes
  precedence while the missing information remains visible.
- [x] Given identical inputs, evaluation returns identical typed output.

## Invariants

- The evaluator performs no I/O and does not mutate its inputs.
- Decision precedence is verified blocker, then missing evidence, then ready.
- Missing evidence is never promoted to a verified blocker.
- Findings reference observed provider fields; an unavailable connector does
  not create fabricated evidence.

## Failure cases

- `None` connector input records unavailable evidence.
- `mergeability="unknown"` records indeterminate GitHub evidence.
- Jira facts for a key different from the GitHub link are not used to make a
  readiness claim; the result records missing applicable Jira evidence.

## Security

The evaluator adds no network, identity, permission, tenant, or persistence
boundary. Callers remain responsible for supplying authorized connector facts.
Evidence contains provider values already present in the input and must be
treated according to the same future authorization rules as those inputs.

## Observability

Runtime logging and tracing are explicit non-goals. Typed reason codes,
findings, missing information, and evidence references provide deterministic
debugging information to a future caller.

## Validation

- `uv run python -m unittest tests.unit.test_merge_readiness_policy -v`
  - Result: 10 policy tests passed.
- `uv run python -m unittest discover -s tests -v`
  - Result: 22 backend tests passed; the existing `TestClient` deprecation
    warning remains.
- `uv run python -m compileall -q app tests`
  - Result: passed with no output.

## Completion notes

The new `app.policy` package is independent of connector lookup and HTTP
orchestration. No dependencies or public routes changed. The fixed V1 approval
requirement is one approval; policy configuration remains future work.
