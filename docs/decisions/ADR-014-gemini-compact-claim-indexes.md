# ADR-014: Compact request-local indexes for Gemini claims

- Status: Accepted
- Date: 2026-08-10
- Owners: Repository owner
- Supersedes: ADR-013 only for Gemini's provider-facing Structured Output schema
- Superseded by: None

## Context

ADR-013 sent the complete `GeneratedExplanation` Pydantic schema through
Google's OpenAI-compatible Structured Output operation. A live request proved
Google rejected that schema because its many enum and length constraints created
too many serving states. Replacing enums with unconstrained strings allowed a
completion, but Gemini returned an empty summary and a reason outside PromptQL's
closed enum. The public policy result and deterministic validator remained
correct, but explanation enrichment failed.

## Decision

- Keep the existing OpenAI SDK, fixed Google URL, Gemini environment names,
  sanitized failure taxonomy, service, strict validator, templates, API, and UI.
- Send Gemini a compact `GeminiExplanationInput` containing the authoritative
  decision and request-local allowed reason/action code arrays.
- Ask Gemini to return `GeminiStructuredClaims`: decision, non-authoritative
  summary, and zero-based reason/action indexes.
- Reject duplicate, negative, and out-of-range indexes inside the adapter.
- Map valid indexes back to the original typed code strings, construct the
  strict `GeneratedExplanation`, then run the unchanged semantic validator.
- Emit one sanitized `llm.explanation.failed` event with bounded provider and
  failure category when a provider call fails.

## Alternatives considered

### Keep the complete enum schema

This preserves maximum provider-side validation but cannot be served by the
current Google compatibility layer, as demonstrated by the live HTTP 400.

### Use unconstrained generated code strings

This schema is accepted by Google, but a live completion invented a value
outside PromptQL's enum. Strict validation correctly rejected it, so this does
not provide a reliable adapter contract.

### Ignore generated claims and copy policy codes

That would always pass but would make the LLM claim-validation harness
meaningless. Request-local indexes still require the model to select claims and
allow the deterministic validator to detect omissions and contradictions.

### Add Google's native SDK

A second production dependency does not remove the provider's schema limit and
adds another transport, error, and lifecycle surface without evidence it is
needed.

## Consequences

The provider sees only code values already inside the minimized allowlist and
returns small positional claims. The adapter adds mapping logic, but generated
indexes cannot invent new codes. Strict Pydantic and semantic validation remain
the authority after provider parsing. Generated prose remains discarded.

Indexes are meaningful only within one request and must never be persisted or
used as durable identifiers. If code ordering changes, both the sent allowlist
and returned indexes still belong to the same in-memory request.

## Invariants

- The policy result, not the provider, determines readiness.
- Invalid or incomplete indexes cannot bypass `GeneratedExplanation` or the
  deterministic validator.
- Provider output, raw errors, credentials, prompts, and payloads are never
  logged, traced, persisted, or returned.
- No fallback, retry, route, schema, database, or frontend behavior is added.

## Reconsideration triggers

Revisit this decision if Google accepts the complete strict schema, claim IDs
become durable, explanations are persisted, or provider-generated prose becomes
eligible for exposure.
