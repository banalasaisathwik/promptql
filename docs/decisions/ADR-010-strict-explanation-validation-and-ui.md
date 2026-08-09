# ADR-010: Strict explanation validation and read-time API enrichment

- Status: Accepted
- Date: 2026-08-09
- Owners: Repository owner
- Supersedes: ADR-009 only for semantic validation and API exposure
- Superseded by: None

## Context

ADR-009 established a provider-neutral explanation harness but deliberately kept
its output internal because shape validation cannot prove that prose is grounded
in policy facts. The repository owner selected strict deterministic templates
before displaying the fake client's output in the frontend.

## Decision

- Backend-owned mappings define exact summary, reason, and action text for every
  policy decision, reason code, and pending-action code.
- `StrictMergeReadinessExplanationValidator` compares the entire generated
  explanation with the expected object. Changed, missing, extra, or reordered
  content is rejected.
- `MergeReadinessResponse` additively enriches the durable runtime run with
  either `explanation` or a sanitized `explanation_error`.
- POST and GET perform the same deterministic enrichment. The explanation is
  not written to the runtime repository and requires no database migration.
- Explanation failure does not change the committed policy result, runtime
  status, or HTTP 200 status of a completed run.
- The frontend validates the new response fields and equality between the
  explanation decision and authoritative policy decision before rendering.

## Alternatives considered

Free-form semantic validation could allow more natural wording, but proving
arbitrary claims would require a larger rule system or another probabilistic
judge. Persisting explanation output would preserve historical wording, but it
would change the runtime schema and ownership before a real provider is chosen.
Displaying shape-valid text without semantic validation was rejected because
unsupported claims could reach users.

## Consequences

The browser can show safe deterministic explanation text with no provider,
credential, network, cost, or migration. The strict validator is intentionally
inflexible: wording improvements require an explicit backend template change.
Read-time regeneration is acceptable only while the fake is deterministic; a
real probabilistic or paid provider requires a new persistence and retrieval
decision.

## Invariants

- The policy result is authoritative; explanation never calculates readiness.
- Only exact accepted template text reaches the browser.
- Rejected output and raw provider errors are not returned or recorded in
  telemetry.
- Failed runtime runs contain neither explanation nor explanation error.
- A completed run contains exactly one explanation outcome.
