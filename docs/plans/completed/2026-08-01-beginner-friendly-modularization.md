# Execution plan: Beginner-friendly connector modularization

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-01
- Last updated: 2026-08-01
- Related ADRs: ADR-001
- Related tasks: V1 connector contracts and connector inspection API/UI

## Objective

Make the implemented connector inspection slice easier for a Python and
TypeScript beginner to navigate without changing observable behavior.

## Current behavior and evidence

The V1 catalog and inspection endpoints work and twelve backend tests pass. The
frontend loads fixtures, submits requests, renders evidence, and passes its
TypeScript/Vite build and lint. Fixture construction is concentrated in one
Python module; frontend types, parsing, transport, orchestration, and rendering
are concentrated in two large TypeScript modules.

## Proposed behavior

Preserve the exact HTTP and UI flow while separating contracts, fixture sources,
application orchestration, HTTP transport, frontend validation, state, form, and
presentation into named modules. Add beginner-oriented module documentation and
reasoning comments at important boundaries.

## Scope

- In scope: internal Python/TypeScript module boundaries, imports, comments,
  tests, architecture map, work record, and learning log.
- Expected systems and files: `services/api/app/connectors`,
  `services/api/app/api`, `services/api/tests`, `apps/web/src`, and `docs`.

## Non-goals

- Endpoint or schema changes, new dependencies, new UI behavior, real
  connectors, merge policy, database, authentication, or deployment changes.

## Acceptance criteria

- [x] Each module has one named responsibility and an explanatory header.
- [x] Python fixture catalog, GitHub fixtures, and Jira fixtures are separate.
- [x] HTTP routes delegate inspection orchestration to an application service.
- [x] Frontend types, validators, transport, form, and response view are separate.
- [x] Existing backend and frontend behavior validation remains green.

## Invariants

- All eight fixture values and ordering remain identical.
- `/v1` paths, request/response JSON, `404`, and `422` remain identical.
- Frontend continues runtime-validating external JSON.
- Comments explain boundaries and syntax without replacing tests or docs.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Broken import | Build/test collection fails | Correct dependency direction |
| Fixture drift | Existing scenario tests fail | Restore exact fixture values |
| Contract drift | API or frontend parser tests fail | Restore public JSON shape |
| UI regression | Build/lint or manual flow fails | Revert component split only |

## Security

No trust or permission boundary changes. Existing Pydantic and browser runtime
validation must remain at external boundaries.

## Observability

Existing loading, error, structured evidence, raw JSON, HTTP statuses, and typed
errors remain unchanged.

## Milestones

1. Python modules are separated and all backend tests pass.
2. TypeScript modules/components are separated and frontend validation passes.
3. Documentation, learning log, final diff, and self-review are complete.

## Validation strategy

Run focused backend tests after Python moves, then full discovery and compile.
Run frontend build, lint, and parser assertions after TypeScript moves. Finish
with `git diff --check` and a final behavior-oriented review.

## Progress

- [x] 2026-08-01: Current flow inspected and module map selected.
- [x] 2026-08-01: Python modularization validated.
- [x] 2026-08-01: TypeScript modularization validated.
- [x] 2026-08-01: Documentation and review completed.

## Decisions and discoveries

- This is an internal Level 1 refactor; ADR-001 remains unchanged.
- Avoid a Python app factory and dependency-injection framework because those
  abstractions would add navigation cost without a current testing need.

## Risks and open questions

- Too many tiny files can be harder than a long file; modules therefore follow
  concrete domain responsibilities rather than individual classes/functions.

## Completion

Python and TypeScript responsibilities are separated according to the documented
module maps. Teaching comments cover module purpose, important syntax, and
boundary reasoning. Backend/frontend validation and final diff review pass; no
observable behavior changed.
