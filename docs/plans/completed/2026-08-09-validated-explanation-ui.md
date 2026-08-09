# Execution plan: Strictly validated explanation API and UI

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-09
- Last updated: 2026-08-09
- Related ADRs: ADR-009, ADR-010
- Related tasks: None

## Objective

Validate fake LLM explanations against exact backend-owned templates, expose
only accepted output through existing run responses, and render it in the
frontend without changing the authoritative policy decision.

## Current behavior and evidence

The internal explanation harness validates Pydantic shape and decision equality
but is not called by the workflow or API. The frontend receives only the flat
typed `MergeReadinessRun`. POST and GET run responses are identical, and the
stored runtime model contains no explanation.

## Proposed behavior

Strict templates derived from policy reason/action codes define the only valid
explanation. The service rejects any mismatch. API-specific response fields add
either the validated explanation or a sanitized explanation error while leaving
the persisted run unchanged. Both POST and GET derive the same deterministic
fake explanation. The frontend validates and renders the added fields.

## Scope

- In scope: templates, strict validator, typed error, safe telemetry category,
  additive API response, POST/GET enrichment, frontend validation/rendering,
  regression tests, ADR/docs/learning/Mermaid updates.
- Expected systems and files: `app/explanations`, observability contracts,
  `app/api/v1`, frontend inspection feature, backend/frontend tests, docs.

## Non-goals

- Real model provider, API key, free-form semantic validation, explanation
  persistence, migration, retries, queues, connectors, or policy changes.

## Acceptance criteria

- [x] Exact ready, blocked, and unknown templates validate.
- [x] Changed, missing, extra, or reordered explanation content is rejected.
- [x] Validated explanation is returned by POST and GET without changing run.
- [x] Explanation failure returns a sanitized explanation error and completed
  policy result rather than changing runtime or policy status.
- [x] Frontend validates and displays every explanation reason/action.
- [x] Frontend never derives or overrides the policy decision.
- [x] Existing backend and frontend suites continue passing.

## Invariants

- The deterministic policy result is authoritative and durably persisted before
  explanation enrichment.
- Only exact backend-owned text reaches the browser.
- POST and GET remain identical under deterministic fake generation.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Provider or shape failure | Completed run plus sanitized explanation error | Policy remains usable; fix provider output |
| Strict template mismatch | No explanation text exposed | Inspect stable validation category, not raw output |
| Frontend contract mismatch | Network validation error, not policy unknown | Fix backend/frontend schema drift |

## Security

No prompt, output rejected by validation, provider exception, connector content,
credential, repository identity, or Jira content enters logs or error bodies.
Only backend-owned accepted templates reach the browser.

## Observability

Reuse the existing model-call span and metrics with a new bounded
`validation_failure` result/failure category. Do not add user-controlled labels
or log explanation text.

## Milestones

1. Implement strict templates/validator and focused backend tests.
2. Add API response enrichment and integration tests.
3. Add frontend validation/rendering/tests, run full verification, and close
   documentation.

## Validation strategy

Run focused validator/harness tests, backend API tests, complete backend
discovery and compileall, then frontend tests, lint, and build. Finish with
`git diff --check`, sensitive-data scan, and explicit PostgreSQL skip reporting.

## Progress

- [x] 2026-08-09: Resolved strict-template validation design and inspected all
  affected backend/frontend boundaries.
- [x] 2026-08-09: Implemented and verified the cross-layer change.

## Decisions and discoveries

The existing POST/GET equality requires deterministic enrichment on both paths.
Explanation response fields remain API-specific rather than modifying the
persisted runtime model or policy result.

## Risks and open questions

- Read-time generation is safe for the deterministic fake but must be
  reconsidered before a paid or probabilistic provider is introduced.

## Completion

Implemented with strict backend-owned templates, additive POST/GET response
enrichment, frontend network validation and rendering, and no persistence
migration. Backend discovery passed 127 tests with four PostgreSQL tests skipped
because `TEST_DATABASE_URL` was absent. Frontend testing passed 10 tests; lint,
TypeScript/Vite build, and Python compile checks passed.
