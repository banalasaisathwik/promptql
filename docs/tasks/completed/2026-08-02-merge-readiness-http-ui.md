# Task: Complete merge-readiness request-to-render flow

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-02
- Related ADRs: ADR-002
- Related execution plan: `docs/plans/completed/2026-08-02-merge-readiness-http-ui.md`

## Objective

Connect the existing fake connector facts to the deterministic policy behind a
typed API and render the returned decision in the frontend.

## Current behavior

The inspection endpoint and UI exposed source facts only. No HTTP route called
`evaluate_merge_readiness()`.

## Scope

- Backend orchestration, endpoint, response contract, partial-unavailability
  handling, frontend client/validation/rendering, and focused tests.

## Non-goals

- Authentication, real connectors, persistence, LLMs, tracing, dashboards, or
  new policy rules.

## Acceptance criteria

- [x] Complete connector-to-policy-to-HTTP workflow exists.
- [x] Frontend displays the exact backend decision prominently.
- [x] Every returned blocker, action, missing item, and evidence reference is
  rendered.
- [x] Raw facts remain available as debug evidence.
- [x] Structured errors and validation remain compatible.

## Invariants

- Neither route nor frontend duplicates policy rules.
- Frontend list contents never determine the overall decision.

## Failure cases

Explicit connector unavailability becomes missing information. Unknown fixtures
remain `404`, invalid requests remain `422`, and frontend transport failures are
shown as errors rather than `unknown`.

## Security

No identity boundary changed. Fixture data remains fictional; real connector
authorization is still not implemented.

## Observability

Typed policy details and frontend errors are visible. Runtime tracing remains a
non-goal.

## Validation

- Backend: 29 tests passed and Python compilation passed.
- Frontend: 7 tests passed, TypeScript/Vite build passed, Oxlint passed.

## Completion notes

The existing facts-only endpoint remains available. The UI now calls only the
dedicated readiness workflow for analysis submissions.
