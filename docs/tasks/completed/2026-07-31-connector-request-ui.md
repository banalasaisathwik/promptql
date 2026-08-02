# Task: Typed connector-request frontend

- Status: Completed
- Owner: Repository owner
- Created: 2026-07-31
- Related ADRs: None
- Related execution plan: None

## Objective

Replace the Vite starter with a TypeScript form that collects and validates the
three fields required by the backend `ConnectorRequest` contract.

## Current behavior

Before this task, the frontend displayed the Vite starter counter. It did not
collect repository or pull-request input.

## Scope

- In scope: typed draft and request models, local validation, accessible form
  errors, JSON preview, responsive presentation, and current-state docs.
- Expected files: `apps/web/src/App.tsx`, `App.css`, `index.css`,
  `connectorRequest.ts`, and relevant documentation.

## Non-goals

- HTTP submission, connector execution, merge-readiness policy, authentication,
  persistence, and a frontend test-runner dependency.

## Acceptance criteria

- [x] Owner, repository, and PR number inputs are available.
- [x] Valid input produces the exact backend-shaped JSON request.
- [x] Empty names and invalid PR numbers produce field-level errors.
- [x] The UI states that it does not send a network request.
- [x] Frontend build and lint commands pass.

## Invariants

- The validated request uses `repository_owner`, `repository_name`, and
  `pr_number`.
- A request contains only trimmed non-empty names and a positive safe integer.
- Preparing a request has no external side effect.

## Failure cases

- Empty or whitespace-only names remain invalid.
- Zero, negative, decimal, exponent, non-numeric, and unsafe PR values remain
  invalid and cannot enter the preview payload.

## Security

This form handles public repository identity only and performs no network call.
Future API code must repeat validation at the trusted backend boundary.

## Observability

Field-level errors and the exact JSON preview make local validation observable.
Runtime logs and metrics are not materially relevant before submission exists.

## Validation

- Exact commands: `bun run build:web`, `bun run lint:web`, and focused Bun
  assertions against `createConnectorRequest`.
- Expected evidence: build and lint succeed; representative valid and invalid
  values satisfy the conversion contract.
- Result: Passed on 2026-07-31.

## Completion notes

The UI prepares a connector request locally. It does not imply that the backend
currently exposes or executes connector requests.
