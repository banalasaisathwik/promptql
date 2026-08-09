# ADR-011: Ground generated explanations in policy codes

- Status: Accepted
- Date: 2026-08-09
- Owners: Repository owner
- Supersedes: ADR-010 only for exact generated-text validation
- Superseded by: None

## Context

ADR-010 made explanation exposure safe by requiring the generated text object
to equal an exact backend template. That fail-closed design prevents unsupported
wording, but the fake and validator share the same template builder and there
is no explicit distinction between untrusted generated claims and validated
claims. Exact prose equality also does not model the validation boundary a
future real provider needs.

Pydantic can validate field types, enum membership, and size bounds. It cannot
prove that generated reasons and actions are supported by the authoritative
`MergeReadinessResult` or that required findings were not omitted.

## Decision

- `GeneratedExplanation` is untrusted client output containing a decision,
  bounded internal summary, reason codes, and action codes.
- `StrictMergeReadinessExplanationValidator.validate()` receives the complete
  policy result and generated output. It compares generated code sets with the
  blocker, missing-information, primary-reason, and pending-action codes in the
  policy result.
- Duplicate generated codes fail before set comparison. Accepted codes are
  returned in policy order as a code-only `ValidatedExplanation`.
- Unsupported, omitted, duplicated, or contradictory claims raise a typed
  `ExplanationValidationError` with a stable bounded failure code.
- Generated prose is discarded. `render_validated_explanation()` creates the
  existing API-facing summary, reasons, and actions from approved templates.
- The current API schema, frontend panel, persistence model, policy evaluator,
  and runtime behavior remain unchanged.
- The explanation span records only validation success or a stable failure
  category. Existing metrics keep their bounded result labels.

## Alternatives considered

### Continue exact generated-text equality

This is simple and safe for the deterministic fake, but it makes harmless text
variation fail and does not model structured grounding for a future provider.

### Validate free-form prose with keywords

Keywords cannot prove meaning, negation, completeness, or factual support. A
sentence can contain an approved word while making the opposite claim.

### Ask another LLM to validate the explanation

Another probabilistic model can repeat the same mistake and can vary across
runs. It would add provider, cost, latency, and failure behavior without making
the boundary deterministic.

## Consequences

The validator can prove that structured decision/reason/action claims exactly
match deterministic policy categories. It cannot prove arbitrary prose, so
generated prose never reaches users. Repeated policy findings with the same
reason code render once; future per-finding explanations would require stable
finding identifiers. Adding a new policy enum requires an approved rendering
template and test coverage.

## Invariants

- The deterministic policy result is the only readiness authority.
- Generated reason/action codes must be supported and complete.
- Ready cannot include remediation; non-ready cannot include the ready reason;
  unknown must include missing-evidence grounding.
- Generated output and validation exceptions never enter API responses,
  persistence, logs, spans, or metric labels.
- Provider, validation, or telemetry failure cannot mutate policy or runtime
  persistence and never causes an automatic retry.
