# ADR-001: Versioned connector inspection API and backend-owned demo catalog

- Status: Accepted
- Date: 2026-07-31
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

The backend owns eight deterministic GitHub/Jira fixture scenarios, while the
frontend can only prepare a connector request locally. The UI needs a dropdown
that cannot drift from backend fixtures and must receive the combined fake
connector response after submission. No connector HTTP API currently exists.

The browser should use production-style relative URLs in development without
adding permissive CORS policy or hardcoding `localhost` in application code.

## Decision drivers

- One authoritative fixture catalog
- Stable boundary that can later call real connectors
- Honest separation of demo fixture discovery from inspection behavior
- Typed success and failure responses
- Same-origin browser URLs in development and production
- Reversible implementation without a new dependency

## Options considered

### Option A: Backend catalog plus separate inspection endpoint

Expose `GET /v1/demo/pull-request-scenarios` for fixture selection and
`POST /v1/pull-request-inspections` for execution. Proxy `/v1` through Vite in
development. This adds two small contracts but prevents catalog duplication and
keeps inspection independent of fixture discovery.

### Option B: One catalog endpoint containing complete responses

Return all GitHub and Jira snapshots in the catalog. This needs only one call,
but selection would not execute a connector lookup and every response would be
downloaded eagerly. Catalog metadata would be coupled to connector output.

### Option C: Frontend-owned catalog plus inspection endpoint

Hardcode labels and requests in TypeScript and expose only the inspection POST.
This is locally simpler but duplicates fixture identity across languages and can
silently drift when backend scenarios change.

## Repository owner reasoning

The owner selected Option A after clarifying that clicking Prepare request must
send one of the hardcoded backend requests and render its inspection response.
The backend therefore needs to remain authoritative for both selectable inputs
and returned fixture data.

## Reasoning review

The reasoning correctly protects fixture consistency and proves a real
frontend-to-backend flow. The fixture list is not a production business
resource, so its route is explicitly scoped under `/demo/`. The inspection
route is not demo-prefixed because its contract can remain valid when fake
connectors are replaced. Option C would fit only a disposable static prototype;
Option B would fit only when lookup execution is not demonstrated.

## Decision

- Add `GET /v1/demo/pull-request-scenarios` returning scenario ID, label, and
  connector request.
- Add `POST /v1/pull-request-inspections` returning request, GitHub snapshot,
  and Jira snapshot.
- Return a typed top-level `404` error for an unknown valid fixture and retain
  FastAPI's `422` validation response for malformed input.
- Use relative `/v1` URLs in the frontend and a Vite development proxy targeting
  the local API.
- Validate API JSON at runtime in the browser in addition to TypeScript types.

## Consequences

- Correctness: fixture selection and lookup share one backend source.
- Complexity: two routes and mirrored frontend response types are required.
- Failure behavior: catalog, validation, not-found, malformed-response, and
  network failures become independently visible.
- Security: only fictional fixture data is exposed; authentication and tenant
  boundaries remain mandatory before real connector access.
- Performance: catalog and fixture payloads are small; the additional request is
  not materially relevant at V1 scale.
- Maintainability: the inspection route can survive replacement of fake
  connectors, while the demo catalog can later be removed or gated.
- Reversibility: routes, proxy, and client are additive and contain no persisted
  state or migration.
- Cost and scalability: not materially relevant for deterministic in-memory
  fixtures.

## Invariants

- Dropdown entries originate only from the backend catalog.
- Inspection responses contain source facts and no merge-readiness conclusion.
- Frontend application code uses relative `/v1` URLs.
- Unknown valid requests return `404`; invalid requests return `422`.

## Validation

- Backend unit and API integration tests
- Frontend runtime-parser assertions, lint, type checking, and Vite build
- Direct HTTP catalog, success, not-found, and validation checks

## Reconsideration triggers

- Real connectors replace fixtures.
- Fixture discovery must not be exposed in a deployed environment.
- Authentication, tenant isolation, or partial connector failure is introduced.
