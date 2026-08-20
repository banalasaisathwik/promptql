# Execution plan: V2.2 first-class evidence and provenance

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-17
- Last updated: 2026-08-17
- Related ADRs: ADR-019, ADR-020
- Related tasks: None

## Objective

Make investigation evidence a strict, immutable, auditable domain entity whose
typed content can support facts and hypotheses without coupling the domain to
provider payloads, storage, transport, or runtime execution.

## Current behavior and evidence

V2.1 is committed as `bcfd55a`. `InvestigationFact` variants and `Hypothesis`
carry evidence IDs, but `InvestigationResult` has no evidence collection and
cannot resolve those references. V1 `EvidenceReference` stores one policy field
and scalar value for GitHub/Jira only; it remains stable and unchanged.

## Proposed behavior

An `Evidence` envelope owns stable identity, logical source, evidence kind,
provenance, and one discriminated typed content value. `InvestigationResult`
owns evidence and rejects duplicate IDs or fact/hypothesis references that do
not resolve inside the result.

## Scope

- In scope: pure investigation-domain models, aggregate invariants, unit tests,
  ADR/plan, architecture/product/testing/learning docs, and local Mermaid flow.
- Expected systems and files: `app/investigations/models.py`, package exports,
  investigation tests, and V2 documentation.

## Non-goals

- No GitHub/Jira/incident/deployment retrieval, adapters, raw payloads,
  persistence, runtime, API, frontend, planner, tools, LLMs, or telemetry.

## Acceptance criteria

- [x] Evidence identity, source, kind, provenance, and content are typed.
- [x] Content is a discriminated union rather than an arbitrary dictionary.
- [x] Timestamps reject naive datetimes while tolerating clock skew.
- [x] Results reject duplicate evidence and broken fact/hypothesis references.
- [x] Missing information needs no fake evidence object.
- [x] Focused evidence, V2.1, and full backend tests pass.
- [x] Documentation marks only V2.2 domain modeling as implemented.

## Invariants

- Evidence and its provenance/content are frozen and reject extra fields.
- Every content type agrees with envelope kind and logical source.
- Facts and direct hypothesis evidence links resolve in the same result.
- Provider payloads are normalized before they can become domain evidence.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Naive timestamp | Pydantic `ValidationError` | Supply a timezone-aware source/retrieval time |
| Kind/content/source mismatch | Pydantic `ValidationError` | Construct the correct normalized content and envelope |
| Duplicate evidence ID | Result validation fails | Assign stable distinct observation identities |
| Broken evidence reference | Result validation fails | Include the evidence or remove the unsupported relation |
| Source data absent | No fake evidence is constructed | Add typed `MissingInformation` |

## Security

The model accepts only normalized typed fields. It has no credential, header,
raw payload, signed URL, or arbitrary dictionary field. External content remains
untrusted until a future adapter validates and normalizes it.

## Observability

No runtime operation exists, so V2.2 adds no spans, metrics, or logs. Future
collection may record bounded source/kind outcomes without exporting content.

## Milestones

1. Implement and narrowly validate envelope/content/provenance contracts.
2. Integrate aggregate references and prove V2.1 compatibility.
3. Document, teaching-comment, fully validate, and archive the plan.

## Validation strategy

Run focused evidence and investigation model tests, compile application/tests,
run complete backend unittest discovery, inspect forbidden constructs and the
final diff, then run `git diff --check`.

## Progress

- [x] 2026-08-17: Verified branch, committed V2.1 baseline, docs, models, and tests.
- [x] 2026-08-17: Implement evidence contracts and aggregate invariants.
- [x] 2026-08-17: Add focused tests and update V2.1 result fixtures (33 focused tests passed).
- [x] 2026-08-17: Update documentation and learning artifacts.
- [x] 2026-08-17: Applied teaching comments; compile, 33 focused tests,
  244 backend tests with 6 environment-guarded skips, and diff checks passed.

## Decisions and discoveries

ADR-020 records the envelope + typed-content decision, optional source-event
time, required retrieval time, clock-skew policy, and unchanged V1 boundary.

## Risks and open questions

- The initial source/kind compatibility map may need an explicit extension when
  a later real adapter produces a legitimate combination not modeled here.

## Completion

V2.2 is implemented and validated as a pure domain-model milestone. The plan is
archived without starting V2.3 provider collection work.
