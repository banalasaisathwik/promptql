# Execution plan: Backend-driven connector inspection flow

- Status: Completed
- Owner: Repository owner
- Created: 2026-07-31
- Last updated: 2026-07-31
- Related ADRs: ADR-001
- Related tasks: V1 connector contracts, typed connector-request frontend

## Objective

Connect the frontend form to deterministic backend fixtures through a typed,
versioned API and render the complete GitHub and Jira inspection response.

## Current behavior and evidence

`services/api/app/main.py` exposes only `/health`. Connector fixtures and fakes
exist internally. `apps/web/src/App.tsx` validates and previews a request without
network I/O. The frontend build, lint, and backend unit suite pass.

## Proposed behavior

The browser loads backend scenario metadata, populates the form from a dropdown,
posts the validated request, runtime-validates the response, and renders GitHub
and Jira facts. Loading, catalog, validation, not-found, malformed-response, and
network states are explicit.

## Scope

- In scope: V1 FastAPI routes/models/error mapping, fixture metadata, API tests,
  Vite proxy, TypeScript API client, dropdown, submission, response display,
  current-state docs, task record, and learning log.
- Expected systems and files: `services/api/app`, `services/api/tests`,
  `apps/web/src`, `apps/web/vite.config.ts`, and `docs`.

## Non-goals

- Merge-readiness policy, real connectors, OAuth, authentication, database,
  retry orchestration, caching, or deployment configuration.

## Acceptance criteria

- [x] Backend catalog returns all eight predefined scenarios.
- [x] Selection fills the exact typed request.
- [x] Submission calls `/v1/pull-request-inspections` and renders GitHub/Jira.
- [x] Unknown valid and malformed requests return `404` and `422` respectively.
- [x] Frontend exposes loading and actionable error states.
- [x] Relevant backend and frontend validation passes.

## Invariants

- Backend fixture metadata is the only dropdown source.
- Relative `/v1` URLs are used in browser code.
- Connector facts remain separate from policy conclusions.
- External response JSON is runtime-validated before rendering.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Catalog unavailable | Dropdown displays load failure | Restart API and reload the page |
| Invalid request | Field validation or API `422` | Correct input |
| Unknown fixture | Typed `404` message | Select a catalog scenario |
| Malformed response | Frontend contract error | Fix API/client contract drift |
| Unexpected server error | Generic request failure | Inspect server output; retry |

## Security

Only fictional fixture data crosses the boundary. Pydantic validates requests;
the browser validates response shapes. Authentication and tenant authorization
are explicitly outside this fake-only slice.

## Observability

The UI shows loading, errors, selected request, and returned evidence. HTTP
status codes and typed bodies support debugging. Production logs and metrics are
not introduced for deterministic local fixtures.

## Milestones

1. Backend routes and integration tests pass.
2. Frontend catalog, submission, response UI, build, and lint pass.
3. Documentation and final diff review are complete.

## Validation strategy

Run backend integration tests first, then full backend discovery. Run focused
frontend API parser assertions, lint, and build. Finish with direct HTTP checks
when practical and `git diff --check`.

## Progress

- [x] 2026-07-31: ADR accepted and implementation plan recorded.
- [x] 2026-07-31: Backend API implemented and tested.
- [x] 2026-07-31: Frontend flow implemented and validated.
- [x] 2026-07-31: Documentation and review completed.

## Decisions and discoveries

- ADR-001 selects separate catalog and inspection routes with a Vite proxy.

## Risks and open questions

- Real connector authentication and partial failure semantics remain deferred.

## Completion

Catalog and inspection routes, frontend request/response flow, runtime boundary
validation, error states, documentation, and tests are complete. Twelve backend
tests, frontend build/lint, parser assertions, compilation, and diff checks pass.
The TestClient dependency warning and all real-connector concerns remain open.
