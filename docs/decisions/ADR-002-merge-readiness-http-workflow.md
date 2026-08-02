# ADR-002: Additive merge-readiness HTTP workflow

- Status: Accepted
- Date: 2026-08-02
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

The deterministic policy exists as a pure Python function, but ADR-001 defines
`POST /v1/pull-request-inspections` as a facts-only endpoint. The frontend can
display a failed CI fact yet cannot display the overall policy decision because
no HTTP boundary invokes the evaluator.

## Decision drivers

- Preserve the accepted raw-inspection contract
- Make the backend the only owner of readiness decisions
- Keep connector errors and request validation structured
- Return raw facts as supporting evidence rather than a substitute conclusion
- Represent partial connector unavailability without fabricating blockers
- Avoid a new dependency

## Options considered

### Option A: Add a dedicated readiness endpoint

Add `POST /v1/pull-request-merge-readiness`. It retrieves typed facts, calls the
existing evaluator, and returns a nested `policy_result` beside optional raw
facts. This adds one route but preserves the existing endpoint and makes the
workflow boundary explicit.

### Option B: Change the inspection endpoint response

Make `/v1/pull-request-inspections` return policy fields. This avoids another
URL but breaks the documented facts-only response model and clients that expect
the original JSON shape.

## Repository owner reasoning

The owner asked for the missing orchestration boundary and delegated the choice
between a dedicated endpoint and conversion based on existing architecture and
documented contracts.

## Reasoning review

ADR-001 explicitly preserves a facts-only inspection response. An additive
endpoint satisfies the complete workflow without silently changing that public
contract. Conversion would be preferable only if the inspection route were
unreleased or explicitly deprecated and migrated.

## Decision

- Add `POST /v1/pull-request-merge-readiness`.
- Return `PullRequestMergeReadiness` containing request, optional GitHub/Jira
  facts, and the complete `MergeReadinessResult` under `policy_result`.
- Use FastAPI dependencies for default fake connectors and deterministic test
  overrides.
- Convert only `ConnectorUnavailableError` into missing policy evidence.
- Preserve `FixtureNotFoundError` as `404` and Pydantic validation as `422`.
- Make the frontend render `policy_result.decision` without deriving it.

## Consequences

- Correctness: one backend workflow owns the decision and supporting facts.
- Compatibility: the existing inspection endpoint remains unchanged.
- Complexity: one route, one response wrapper, and connector dependency
  providers are added.
- Failure behavior: unavailable evidence can return `unknown`; verified
  blockers still take precedence; unknown fixtures remain `404`.
- Security: the endpoint currently exposes fictional fixtures only. Future real
  connector facts and evidence require authentication and authorization.
- Performance: two in-memory lookups and one pure evaluation are not materially
  relevant at fixture scale.
- Reversibility: the additive endpoint can be removed without migrating stored
  state because no persistence exists.

## Invariants

- The route and frontend contain no policy rules.
- `policy_result.decision` is the only displayed overall decision.
- All blockers, actions, missing information, and evidence references are
  preserved.
- Raw connector facts remain supporting/debug evidence.
- Not-found and validation errors retain their existing HTTP behavior.

## Validation

- 29 backend tests through `unittest` discovery
- 7 frontend Bun tests
- Python compilation, TypeScript/Vite build, and Oxlint

## Reconsideration triggers

- The facts-only endpoint is formally deprecated.
- Real connector failures need richer retry or permission metadata.
- Authentication or tenant boundaries are introduced.
