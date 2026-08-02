# Execution plan: Merge-readiness HTTP and UI flow

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-02
- Last updated: 2026-08-02
- Related ADRs: ADR-001, ADR-002
- Related tasks: `docs/tasks/completed/2026-08-02-merge-readiness-http-ui.md`

## Objective

Expose the existing deterministic policy through a typed HTTP workflow and
render its exact result in the frontend.

## Current behavior and evidence

The frontend called `/v1/pull-request-inspections`, whose response contained
only `request`, `github`, and `jira`. Failed CI rendered as a source fact but no
overall decision was available.

## Proposed behavior

```text
request -> fake connectors -> typed facts -> policy -> typed HTTP response
        -> runtime browser validation -> exact decision and complete findings
```

## Scope

- Dedicated readiness route, orchestration, partial unavailability, typed
  response, frontend transport/validation/rendering, and tests.

## Non-goals

- Real connectors, authentication, persistence, LLMs, tracing, charts, or
  frontend policy calculations.

## Acceptance criteria

- [x] Failed CI returns and renders `blocked`.
- [x] Merge-ready facts return and render `ready`.
- [x] Missing evidence returns and renders `unknown`.
- [x] A blocker wins over unavailable evidence.
- [x] Existing `404` and `422` behavior remains.
- [x] Frontend renders all findings and never derives the decision.

## Invariants

- Backend policy result owns the decision.
- Connector facts are evidence, not a frontend policy input.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Unknown fixture | Typed `404` | Correct the request or add a fixture |
| Invalid request | FastAPI `422` | Correct form values |
| Connector unavailable | `unknown` unless a blocker is known | Retry evidence retrieval |
| Network/backend failure | Explicit frontend error | Retry after backend recovery |

## Security

Only fictional fixture evidence is currently exposed. Real data requires a
separate authorization and tenant-boundary decision.

## Observability

Runtime tracing is out of scope. Typed errors and policy evidence provide the
current debugging surface.

## Milestones

1. Typed backend orchestration and HTTP integration tests.
2. Typed frontend transport, rendering, tests, and documentation.

## Validation strategy

- `uv run python -m unittest discover -s tests -v`
- `uv run python -m compileall -q app tests`
- `bun run test:web`
- `bun run build:web`
- `bun run lint:web`

## Progress

- [x] 2026-08-02: Backend workflow and seven HTTP tests completed.
- [x] 2026-08-02: Frontend workflow and seven Bun tests completed.

## Decisions and discoveries

ADR-002 records why the new endpoint is additive. Bun and React server rendering
provided useful frontend tests without a new test dependency.

## Risks and open questions

- A browser DOM test runner may become useful when interaction complexity grows.

## Completion

All commands in the validation strategy passed. The existing Starlette
`TestClient` deprecation warning remains and no dependency was added for it.
