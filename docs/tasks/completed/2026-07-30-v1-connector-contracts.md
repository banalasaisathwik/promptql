# Task: V1 connector contracts and deterministic fakes

- Status: Completed
- Owner: Repository owner
- Created: 2026-07-30
- Related ADRs: None
- Related execution plan: None

## Objective

Define the first validated GitHub and Jira connector contracts, deterministic
fake implementations, scenario fixtures, and focused unit tests.

## Current behavior

Before this task, the API exposed only `GET /health`. It had no connector
models, fake connectors, fixtures, or backend tests.

## Scope

- In scope: Pydantic request and response models, enums, typed fixture lookup
  failure, deterministic GitHub and Jira fakes, eight requested scenarios, and
  unit tests.
- Expected files: `services/api/app/connectors`,
  `services/api/tests/unit`, and current architecture/testing documentation.

## Non-goals

- Merge-readiness policy, LLMs, databases, API routes, OAuth, network calls,
  and real GitHub or Jira connectors.

## Acceptance criteria

- [x] Valid predefined fixture data passes Pydantic validation.
- [x] Invalid enum values and PR numbers fail validation.
- [x] Unknown repository/PR identities raise `FixtureNotFoundError`.
- [x] Repeated equal requests return equal GitHub and Jira snapshots.

## Invariants

- Connector requests use an exact owner, repository, and positive PR identity.
- Predefined-valued response fields use enums.
- Fixture values are validated, frozen, and contain no runtime randomness.
- Fake responses describe source facts and do not calculate merge readiness.

## Failure cases

- Invalid request or response data raises Pydantic `ValidationError`.
- A valid but unknown fixture identity raises `FixtureNotFoundError` with the
  connector name and request.

## Security

The contracts reject extra fields and validate boundary values. This slice has
no credentials, authorization, tenant boundary, network I/O, or sensitive data.

## Observability

Typed exceptions make lookup failures inspectable by a future caller. Runtime
logging and metrics are not materially relevant for these in-memory unit fakes.

## Validation

- Exact command: `uv run python -m unittest discover -s tests -v`
- Expected evidence: all connector-contract tests pass.
- Result: 7 tests passed on 2026-07-30.

## Completion notes

The implementation remains internal to the API package. No HTTP behavior,
production dependency, or external system behavior changed.
