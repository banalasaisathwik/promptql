# Task: Beginner-friendly connector modularization

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-01
- Related ADRs: ADR-001
- Related execution plan: `docs/plans/completed/2026-08-01-beginner-friendly-modularization.md`

## Objective

Make the connector inspection implementation easier for a Python and TypeScript
beginner to navigate while preserving all behavior.

## Current behavior

Before this refactor, one Python fixture file contained catalog and both provider
payloads; large frontend modules combined types, parsing, transport, state, and
rendering.

## Scope

- In scope: internal module moves, application-service boundary, React component
  extraction, teaching comments, tests/imports, architecture map, and learning
  record.
- Expected files: backend connector/inspection/API modules, frontend inspection
  feature modules, existing tests, and documentation.

## Non-goals

- Public API, UI behavior, fixture data, dependency, database, authentication,
  real connector, or deployment changes.

## Acceptance criteria

- [x] Python catalog, GitHub fixtures, and Jira fixtures are separate.
- [x] HTTP routes delegate connector orchestration to application functions.
- [x] Frontend types, validators, transport, state, form, and response view are
  separate modules.
- [x] Important modules and non-obvious syntax have beginner-oriented comments.
- [x] Existing backend and frontend validations remain green.

## Invariants

- All endpoint paths, JSON, statuses, fixture values, ordering, and frontend
  behavior remain unchanged.
- Pydantic and browser runtime validation remain at external boundaries.

## Failure cases

- Broken imports fail test discovery or frontend compilation.
- Fixture movement errors fail scenario/API tests.
- Response-contract drift fails runtime parser assertions.

## Security

No boundary changed. The refactor retains request and response validation and
introduces no credentials or external provider access.

## Observability

Existing UI loading/errors, raw response, structured facts, typed errors, and
HTTP statuses remain unchanged.

## Validation

- Backend unittest discovery and compilation: passed.
- Frontend build and Oxlint: passed.
- Focused frontend request/response boundary assertions: passed.
- Final diff check: recorded after final review.

## Completion notes

The refactor favors plain functions and concrete feature modules. It deliberately
does not introduce dependency injection, shared helper frameworks, or index-file
re-export layers that would hide where behavior lives.
