# ADR-027: Resolve code locations from Evidence identities

- Status: Accepted
- Date: 2026-08-21

## Context

V2 can validate that a changed file is related to an observed failure, but it
did not have a bounded code-diagnosis boundary or structured developer
remediation. A model can help classify a plausible code concern, but file paths,
line numbers, functions, and hunks already belong to normalized Evidence.

Live OpenRouter probes demonstrated the risk directly: schema-valid candidates
copied complete Fact/Evidence support after prompt clarification, yet combined
or invented numeric location fields. Deterministic validation correctly rejected
those candidates.

## Decision drivers

- Make fabricated numeric coordinates unrepresentable in provider output.
- Keep code excerpts bounded and relevant to accepted hypotheses.
- Preserve explicit uncertainty: a finding is suspected, not a proven cause.
- Keep recommendations read-only, structured, and grounded.
- Reuse the typed LLM client and deterministic validation pattern.

## Options considered

### Option A: Let the model emit complete code coordinates

The validator could compare every file, line, function, and hunk with Evidence.
This retains a convenient output shape but asks the model to repeat data that the
backend already owns. Live probes showed avoidable coordinate mismatches.

### Option B: Let the model select an Evidence identity

The candidate supplies `location_evidence_id` plus bounded semantic category and
support IDs. Validation resolves that identity and copies exact coordinates from
the observed stack frame, hunk, or changed-file Evidence into the validated
finding. The model still proposes interpretation; deterministic code owns
identity, location, support, persistence, and eventual rendering.

### Option C: Derive every code finding deterministically

This would eliminate the provider boundary but could only restate existing
file/stack relationships. It would not provide the bounded semantic
classification that motivates a separate diagnosis stage.

## Decision

Choose Option B. `CodeContextBuilder` exposes at most twenty relevant locations
and twenty truncated lines per hunk. It also provides complete support bundles
computed from each accepted hypothesis and its Facts. `SuspectedCodeFinding`
selects a location Evidence ID and proposes a closed category. The deterministic
validator requires the exact hypothesis support, the full Fact-to-Evidence
relationship, an observed changed file and failure file, and a selected location
on the same path. It then constructs `ValidatedCodeFinding` coordinates from
Evidence.

Developer recommendations are generated from validated finding categories by
backend-owned enum-to-template mappings. Candidate explanation prose is never
used as product wording, and V2 does not execute remediation.

## Consequences

- A provider cannot place a finding at an invented line because line numbers are
  absent from its output schema.
- Context duplicates a small number of support IDs to make the provider boundary
  explicit and reliable.
- A finding can be grounded while still being semantically incorrect; offline
  reference-answer evals must measure that separately.
- The new component is provider-neutral and task-routed, but workflow/API/UI
  integration is a separate phase.
- No dependency, database migration, write tool, or new service is introduced.

## Security and privacy

Only locations relevant to accepted hypothesis paths cross the model boundary.
Diff lines are capped at twenty and three hundred characters each. External code
and incident text remain untrusted data under system instructions. Credentials,
provider payloads, headers, and unrelated repository content are excluded.

## Validation

- Component tests cover deterministic context, hard bounds, malformed schemas,
  support/evidence relationships, duplicate identities, fabricated paths, and
  location IDs outside the support bundle.
- Candidate schemas cannot contain numeric coordinates or function names.
- Deterministic recommendation tests prove stable codes, IDs, messages, and
  support references.
- A bounded OpenRouter smoke with `openai/gpt-oss-120b` passed provider, schema,
  and grounding gates with one accepted finding and zero rejections.

## Reconsideration triggers

Revisit if a future repository-code connector provides first-class symbol IDs,
if multi-file findings become a measured product requirement, or if evals show
that semantic categories add no value beyond deterministic relationships.
