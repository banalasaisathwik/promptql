# Task: Backend-driven connector inspection API and UI

- Status: Completed
- Owner: Repository owner
- Created: 2026-07-31
- Related ADRs: ADR-001
- Related execution plan: `docs/plans/completed/2026-07-31-connector-inspection-flow.md`

## Objective

Populate the frontend scenario dropdown from backend fixtures and render the
combined GitHub/Jira response returned after submission.

## Current behavior

Before this task, fixtures existed only inside Python and the frontend prepared
a request without network I/O.

## Scope

- In scope: versioned catalog and inspection routes, typed errors, API tests,
  Vite proxy, runtime-validating TypeScript client, dropdown, loading/errors,
  evidence display, ADR, architecture/testing docs, and learning record.
- Expected files: backend API/connectors/tests, frontend source/config, and docs.

## Non-goals

- Merge-readiness policy, real connectors, OAuth, authentication, persistence,
  retries, caching, and production deployment configuration.

## Acceptance criteria

- [x] All eight scenarios are loaded from the backend.
- [x] Selecting a scenario populates its exact request.
- [x] Prepare request calls the versioned inspection endpoint.
- [x] GitHub and Jira facts render in the frontend.
- [x] Unknown valid and malformed requests return `404` and `422`.
- [x] Loading, catalog, request, and malformed-response failures are visible.

## Invariants

- Fixture dropdown data has one backend source.
- Browser URLs are relative `/v1` paths.
- Returned evidence contains no merge-readiness conclusion.
- Both Pydantic and the browser validate their external boundaries.

## Failure cases

- Catalog/network failure produces an actionable frontend message.
- Unknown fixture produces the typed API message.
- Malformed response is rejected before rendering.
- Unexpected fixture or API failures do not expose internal exception details.

## Security

Only fictional fixture data is exposed. No identity, permission, credential, or
tenant boundary exists yet; those remain prerequisites for real connectors.

## Observability

The UI exposes loading, failure, raw response, and structured GitHub/Jira facts.
HTTP statuses and stable error codes make expected failures inspectable.

## Validation

- `uv run python -m unittest discover -s tests -v`: 12 tests passed.
- `uv run python -m compileall -q app tests`: passed.
- `bun run build:web`: passed.
- `bun run lint:web`: passed.
- Focused TypeScript runtime-parser assertions: passed.
- `git diff --check`: recorded after final review.

## Completion notes

FastAPI TestClient emits a Starlette deprecation warning recommending `httpx2`.
No dependency was added; the current integration tests pass. Real connector
failure, authentication, and deployment routing remain deferred.
