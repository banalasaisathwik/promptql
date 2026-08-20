# ADR-019: Typed investigation domain contracts

- Status: Accepted
- Date: 2026-08-16
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

V1 represents deterministic merge-readiness conclusions, but open-ended incident
investigation needs a separate vocabulary for verified facts, candidate
hypotheses, missing information, and recommended follow-up. V2.1 must introduce
that vocabulary without adding a second runtime lifecycle, persistence model,
planner, provider contract, or LLM-owned result.

## Decision drivers

- Facts must carry machine-readable meaning rather than prose alone.
- Hypotheses must remain visibly distinct from authoritative facts.
- Invalid identifiers and broken cross-references must fail at construction.
- The first taxonomy must be small enough to revise as real workflows arrive.
- Existing immutable Pydantic contract conventions should remain consistent.
- V2.2 must be able to add evidence provenance without redesigning fact identity.

## Options considered

### Option A: One prose-oriented fact and hypothesis shape

A single model would be compact, but deterministic code and evals would need to
parse prose to understand a changed file, deployment, or stack frame. That moves
meaning out of the schema and makes invalid combinations difficult to reject.

### Option B: Minimal discriminated fact union and typed investigation entities

Use three initial fact variants with a discriminator, categorical confidence and
grounding status, stable codes, opaque future evidence references, and a result
validator for identity and cross-reference integrity. This adds several small
models but keeps semantics machine-readable and uncertainty explicit.

### Option C: Full incident ontology and generic runtime integration

A broad taxonomy could anticipate more providers, but there is no implemented
workflow evidence for its boundaries. Runtime integration would also mix V2.1
domain language with later execution and persistence milestones.

## Repository owner reasoning

The owner explicitly selected strongly typed facts (Option B), requested a
minimal taxonomy, and required reuse of V1 contract patterns without duplicating
runtime lifecycle concepts. The owner also required hypotheses and their
grounding to remain non-authoritative.

## Reasoning review

The selected direction correctly preserves machine validation, explicit
uncertainty, and a deterministic acceptance boundary. A universal root-cause
enum would be premature, so hypothesis codes remain constrained but extensible.
Evidence existence cannot be checked until V2.2 owns evidence records; V2.1 can
only validate non-empty reference identifiers and internal domain references.

## Decision

Create `app.investigations.models` as a pure domain module. Reuse
`ContractModel` and `NonEmptyString`. Define changed-file, deployment, and stack-
frame facts as a discriminated union; typed hypothesis, missing-information, and
recommended-action entities; and an `InvestigationResult` that validates global
entity ID uniqueness and internal references.

Do not define `InvestigationRun`, `InvestigationStatus`, persistence, APIs,
connectors, planners, tools, LLM output schemas, or evidence records in V2.1.

## Consequences

- Deterministic code can branch on fact variants and stable codes without prose parsing.
- A hypothesis may be well grounded while still not being proven correct.
- V2.2 can resolve opaque evidence IDs against first-class evidence records.
- Adding a fact variant later changes the union and its consumers explicitly.
- Result validation is linear in the number of entities and references; at the
  intended small investigation-result size, performance is not materially relevant.
- No new dependency, database migration, network boundary, or operational service exists.

## Invariants

- All contracts are immutable and reject unexpected fields.
- Every fact has at least one non-empty future evidence reference.
- Supported, weakly supported, and contradicted hypotheses cite a fact or evidence.
- Entity identifiers are globally unique within one result.
- Every internal fact, hypothesis, and missing-information reference resolves.
- An insufficient-evidence result may contain unknowns without inventing facts or hypotheses.
- Domain results contain no runtime lifecycle fields.

## Validation

- Focused model tests construct valid values and reject malformed or inconsistent states.
- Full backend discovery proves existing V1 contracts remain compatible.
- Python compilation and `git diff --check` verify syntax and patch integrity.

## Reconsideration triggers

Revisit the initial fact variants when V2.2 evidence or V2.6 baseline execution
demonstrates a missing semantic shape. Revisit shared runtime abstractions only
after a real `InvestigationRun` exposes concrete overlap with `MergeReadinessRun`.
