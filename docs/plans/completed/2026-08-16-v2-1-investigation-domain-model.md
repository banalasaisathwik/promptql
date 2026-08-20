# Execution plan: V2.1 investigation domain model

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-16
- Last updated: 2026-08-16
- Related ADRs: ADR-019
- Related tasks: None

## Objective

Define the smallest strict, immutable, machine-readable investigation vocabulary
needed before V2 introduces evidence persistence, execution, planning, or LLM
hypothesis generation.

## Current behavior and evidence

`app.connectors.models` owns `ContractModel`, `NonEmptyString`, normalized facts,
and strict validation. `app.policy.models` owns deterministic V1 conclusions and
stable codes. `app.runtime.models` owns generic run/step lifecycle data around a
`MergeReadinessResult`. No `app.investigations` package currently exists.

## Proposed behavior

Pydantic validates an `InvestigationRequest`, one of three discriminated typed
fact variants, candidate hypotheses, explicit missing information, recommended
actions, and an `InvestigationResult` that rejects duplicate identities and
broken internal references.

## Scope

- In scope: pure Python domain models, model tests, ADR, architecture/testing/
  learning documentation, and a local Mermaid domain flow.
- Expected systems and files: `services/api/app/investigations`, backend unit
  tests, `docs/ARCHITECTURE.md`, `docs/TESTING.md`, decision register, learning log.

## Non-goals

- No API DTO or route, database model/table, runtime run, connector, evidence
  record, planner, tool, LLM schema, eval, retry, worker, or frontend behavior.

## Acceptance criteria

- [x] Typed fact meaning does not depend on prose.
- [x] Facts, hypotheses, unknowns, actions, and their references are validated.
- [x] Insufficient evidence is representable without an invented hypothesis.
- [x] No V1 runtime model is duplicated or generalized.
- [x] Focused and complete backend tests pass.
- [x] Current documentation clearly distinguishes implemented V2.1 from deferred V2.

## Invariants

- Contracts are frozen, reject extras, and use stable codes.
- Internal references resolve and entity IDs are unique within a result.
- Grounding describes current support, not objective root-cause correctness.
- The deterministic application will eventually assemble the authoritative result.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Invalid field or enum | Pydantic raises `ValidationError` | Correct the caller's structured value |
| Duplicate entity ID | Result construction fails | Assign distinct stable IDs |
| Broken internal reference | Result construction fails | Include the referenced entity or remove the relation |
| Future evidence ID is unknown | Not checked until V2.2 | Resolve against the future evidence collection |

## Security

These models create no network or authorization boundary. Future external and
LLM content remains untrusted until deterministic code constructs validated
domain values. The contracts contain no secrets or raw provider payloads.

## Observability

No telemetry is added because V2.1 performs no runtime operation. Future run
telemetry may count validated outcomes without serializing claims or evidence.

## Milestones

1. Implement and narrowly test the pure domain contracts.
2. Document, teach-comment, fully validate, and complete the work record.

## Validation strategy

Run `python -m unittest tests.unit.test_investigation_models -v`, compile the
application/tests, then run complete backend unittest discovery and diff checks.

## Progress

- [x] 2026-08-16: Inspected V1 contracts, validators, tests, docs, and dirty worktree.
- [x] 2026-08-16: Implement models and focused tests (16 tests passed).
- [x] 2026-08-16: Update documentation and learning artifacts.
- [x] 2026-08-16: Apply teaching comments and complete validation.

## Decisions and discoveries

ADR-019 records the resolved minimal discriminated-union design and explains
why evidence existence validation is deferred to V2.2.

## Risks and open questions

- The first three fact variants may not cover V2.6; add variants only when an
  implemented workflow demonstrates a stable semantic need.

## Completion

V2.1 is complete as a pure domain boundary. The focused suite passed 16 tests;
complete backend discovery passed 227 tests with six environment-guarded
PostgreSQL skips; `compileall` and `git diff --check` passed. The final teaching-
comment pass annotated the non-obvious Pydantic and aggregate-validation
boundaries without changing behavior. V2.2 first-class evidence remains next.
