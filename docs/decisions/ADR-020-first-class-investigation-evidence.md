# ADR-020: First-class investigation evidence envelope

- Status: Accepted
- Date: 2026-08-17
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

V2.1 introduced typed facts and hypotheses that carry opaque evidence reference
IDs. It could validate identifier syntax but could not prove that those IDs
referenced evidence inside the same result. V1 has `EvidenceReference`, a narrow
merge-policy trace from a provider field to a scalar value; changing it would
risk a stable workflow and still would not add the provenance or typed content
needed by open-ended investigation.

V2.2 needs an auditable, provider-neutral evidence contract without implementing
provider retrieval, persistence, runtime execution, API routes, or raw-payload
storage.

## Decision drivers

- Evidence must remain distinct from facts and hypotheses.
- Provenance must answer source, stable source reference, source-event time, and retrieval time.
- Content must be machine-readable without `dict[str, Any]` payloads.
- Facts and hypotheses must not reference nonexistent evidence in a final result.
- Provider SDK/HTTP schemas and secrets must stay outside the domain.
- The first content taxonomy must be small but useful for V2.3 GitHub code evidence.
- Existing V1 policy contracts and tests must remain unchanged.

## Options considered

### Option A: One evidence class per evidence kind

Each class would repeat identity and provenance fields. Individual schemas would
be direct, but every new kind would duplicate envelope behavior and risk
inconsistent timestamp or source-reference rules.

### Option B: Shared Evidence envelope with a typed content union

One immutable envelope owns identity, logical source, kind, provenance, and a
discriminated content union. Content variants own only kind-specific normalized
fields. This adds one level of nesting but centralizes audit and validation rules.

### Option C: Generic envelope with arbitrary dictionary payload

This is easy to extend but moves required fields, type safety, validation, eval
comparability, and safe serialization into every consumer. It also encourages
raw provider payload retention and provider-schema coupling.

## Repository owner reasoning

The owner preferred Option B, required strongly typed content, explicit
provenance, immutable evidence, timezone-aware timestamps, result-level
cross-reference checks, and no provider collection or persistence in V2.2.

## Reasoning review

Option B preserves one audit envelope while making each content shape explicit.
The initial variants cover only changed files, commits, Jira issues, stack
frames, and deployments. A source/kind compatibility map prevents invalid
combinations in the current vocabulary. If a future provider legitimately
supplies another combination, extending the enum/map is explicit and reviewable.

`observed_at` must be optional because some sources do not provide event time;
`retrieved_at` is required because PromptQL always knows when an observation was
obtained. Both are timezone-aware. V2.2 does not require `retrieved_at >=
observed_at` because distributed clock skew can make strict ordering reject a
truthful observation.

## Decision

Add `Evidence`, `EvidenceProvenance`, typed source/kind enums, and a small
discriminated `EvidenceContent` union to `app.investigations.models`.
`InvestigationResult` owns a tuple of evidence and validates evidence identity,
global entity identity, and every fact/hypothesis evidence reference.

Leave V1 `EvidenceReference` unchanged. Store normalized fields only—never raw
provider dictionaries, credentials, authorization metadata, or arbitrary
confidence values.

## Consequences

- A result is self-contained and auditable at the domain level.
- Downstream fact builders and evals can branch on typed content safely.
- Adding a kind requires a content model, union member, enum, source rule, and tests.
- Envelope/content kind duplication is deliberate: the envelope is queryable
  without inspecting content, while validation prevents disagreement.
- Cross-reference validation remains linear in result size and is not materially
  relevant at the expected small per-investigation scale.
- No dependency, migration, network operation, telemetry, or deployment change exists.

## Invariants

- Evidence is immutable and rejects unexpected fields.
- Evidence IDs and source references are non-empty and bounded.
- `retrieved_at` and optional `observed_at` are timezone-aware.
- Evidence kind matches its discriminated content kind.
- Evidence source is compatible with the current content kind.
- Duplicate evidence IDs are invalid.
- Fact and hypothesis evidence references resolve within the same result.
- Missing data is `MissingInformation`, not an evidence value of `None`.
- Evidence carries no arbitrary confidence or raw provider payload.

## Validation

- Focused evidence tests cover construction, union/source/kind mismatches,
  timestamps, immutability, identity, references, and explicit missing information.
- Existing V2.1 tests are updated only where self-contained evidence is now required.
- Complete backend discovery proves V1 behavior remains compatible.
- `compileall` and `git diff --check` verify syntax and patch integrity.

## Reconsideration triggers

Revisit source/kind compatibility when a real adapter produces a legitimate new
combination. Revisit content variants when V2.3 retrieval exposes a stable field
requirement. Decide raw snapshot/versioning separately only if debugging or
replay evidence justifies its privacy and storage costs.
