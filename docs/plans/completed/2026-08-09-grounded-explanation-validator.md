# Execution plan: Grounded merge-readiness explanation validation

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-09
- Last updated: 2026-08-09
- Related ADRs: ADR-009, ADR-010, ADR-011
- Related tasks: None

## Objective

Replace exact generated-text equality with deterministic validation of
LLM-generated reason and action codes against the authoritative policy result,
then render the existing API-facing wording only from approved templates.

## Current behavior and evidence

`FakeLLMClient` calls the same strict template builder used by the validator.
`StrictMergeReadinessExplanationValidator` compares complete text objects built
from minimized input. This rejects any wording difference, but it does not
separate untrusted generated claims from validated claims or report stable
semantic failure categories. ADR-010 already exposes only exact deterministic
template output through the API and frontend.

## Proposed behavior

The client returns a bounded `GeneratedExplanation` containing untrusted prose
and stable reason/action codes. The service parses that structure and passes it
with the complete `MergeReadinessResult` to the deterministic validator. The
validator rejects unsupported, missing, duplicated, or contradictory codes and
returns a code-only `ValidatedExplanation` in policy order. Approved templates
then render the unchanged public `MergeReadinessExplanation` shape. Generated
prose is discarded and never exposed.

## Scope

- In scope: internal explanation models, validator, service, fake, sanitized
  failure taxonomy, bounded span attributes, focused tests, ADR/docs/learning,
  and the ignored Mermaid flow.
- Expected systems and files: `services/api/app/explanations`, observability
  allowlists, explanation tests, architecture/testing/decision/learning docs.

## Non-goals

- No API or frontend schema/behavior changes, database migration, real model
  provider, retry, fallback, persistence, prompt management, policy change,
  connector change, or unrelated refactor.

## Acceptance criteria

- [x] Ready, blocked, and unknown generated claims validate deterministically.
- [x] Decisions, reasons, actions, blockers, missing evidence, and required
  actions cannot be changed, invented, duplicated, contradicted, or omitted.
- [x] Empty, malformed, and oversized generated fields fail closed.
- [x] Final user-facing text comes only from approved templates.
- [x] Stable validation telemetry contains no prose or external values.
- [x] Existing API schema and frontend rendering remain unchanged.

## Invariants

- The immutable policy result is the only merge-readiness authority.
- Generated prose is untrusted and never returned, logged, traced, or stored.
- The fake client passes through the same parser and validator as any provider.
- Validation and telemetry failures cannot modify runtime persistence or policy.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Generated shape invalid | Existing sanitized explanation error | Correct provider contract; no retry |
| Unsupported or missing code | Existing sanitized explanation error | Correct generated claims; policy remains usable |
| Telemetry failure | Explanation behavior unchanged | Inspect sanitized telemetry warning |

## Security

Only the existing minimized decision/reason/action input crosses the client
boundary. Generated prose, raw output, connector values, repository identity,
credentials, headers, and exception messages are excluded from API responses,
persistence, logs, spans, and metric labels.

## Observability

The existing explanation span records bounded validation result and stable
failure-category attributes. Existing duration/token metrics remain bounded;
no user-controlled or output-derived labels are added.

## Milestones

1. Implement generated/validated contracts and deterministic validator with
   focused adversarial tests.
2. Integrate service/fake/telemetry, preserve API behavior, complete docs and
   full backend/frontend verification.

## Validation strategy

Run focused explanation tests first, then API regressions, complete backend
discovery, Python compilation, frontend test/lint/build, `git diff --check`, and
a final secret/output exposure review. PostgreSQL tests may skip only when the
guarded `TEST_DATABASE_URL` is absent.

## Progress

- [x] 2026-08-09: Inspected current models, service, validator, fake, policy,
  telemetry, API behavior, tests, ADRs, and learning documentation.
- [x] 2026-08-09: Implemented and verified grounded validation.

## Decisions and discoveries

Option A preserves ADR-010's public response. Code sets establish semantic
support and completeness; the validator detects duplicates before set
comparison and canonicalizes accepted codes into policy order.

## Risks and open questions

- One reason code can represent multiple findings of the same category. A
  future per-finding explanation contract would require stable finding IDs.

## Completion

Implemented with separate generated/validated contracts, code-set grounding,
stable sanitized validation categories, deterministic rendering, and unchanged
API/frontend behavior. The focused suite passed 21 tests; backend discovery ran
137 tests with four guarded PostgreSQL skips; frontend tests, lint, build, and
Python compilation passed. Final diff and security review found no generated
prose, credentials, provider output, or external values crossing telemetry,
persistence, or the API boundary.
