# ADR-030: OpenRouter through the OpenAI-compatible explanation boundary

- Status: Accepted
- Date: 2026-08-25
- Owners: Repository owner
- Extends: ADR-016 and ADR-017 with a fourth real explanation provider identity
- Superseded by: None

## Context

ADR-017 added Groq as a third real explanation provider behind `LLMClient`,
reusing the OpenAI SDK with a fixed compatibility base URL. `LLMTask`/model
routing (`docs/plans/completed/2026-08-20-openrouter-model-routing.md`)
separately added OpenRouter as an OpenAI-compatible endpoint for the V2
planner and hypothesis-generation workloads, but that work did not touch the
V1 merge-readiness explanation boundary or `ExplanationSource` provenance.
This session adds OpenRouter as an explanation-generation provider identity
for that same V1 boundary, alongside `fake`, `gemini`, `groq`, and `openai`.

## Decision

- Add explicit `openrouter` provider identity (`LLMProvider.OPENROUTER` in
  `app/config.py`) with `OPENROUTER_API_KEY`/`OPENROUTER_MODEL` configuration,
  following the same required-when-selected pattern as Groq.
- Reuse the installed OpenAI Python SDK with the fixed
  `https://openrouter.ai/api/v1` base URL and `max_retries=0`
  (`app/explanations/factory.py`).
- Implement `OpenRouterLLMClient` (`app/explanations/openrouter_client.py`) as
  a subclass of `GroqLLMClient` rather than a parallel duplicate: it reuses
  the Groq adapter's Chat Completions structured-output request/response
  handling in full and overrides only provider identity
  (`LLMProviderName.OPENROUTER`) and disables Groq's reasoning-effort request
  option, which OpenRouter does not support.
- Extend the durable `explanation_source` vocabulary
  (`ExplanationSource` in `app/runtime/models.py`) with `openrouter`, following
  the same additive pattern ADR-017 used to add `groq`.

## Consequences

- OpenRouter becomes independently configurable and observable without a new
  dependency, public schema, policy, service, validator, or renderer change,
  matching ADR-017's consequences for Groq.
- Because `OpenRouterLLMClient` subclasses `GroqLLMClient` instead of
  duplicating it, provider-specific behavior is isolated to two class
  attributes rather than a second copy of request/error-mapping logic.
- The Python `ExplanationSource` enum, migration
  `20260825_0005_add_openrouter_explanation_source.py`, and the
  `ck_workflow_runs_explanation_source` check constraint declared in
  `app/database/models.py` all agree on the same five-value vocabulary
  (`fake`, `gemini`, `groq`, `openai`, `openrouter`). A run explained by
  OpenRouter durably records that provenance.

## Invariants

- The deterministic policy result remains the only readiness authority.
- OpenRouter receives only minimized stable policy codes and a fixed
  instruction, matching every other provider.
- `OPENROUTER_API_KEY` is sent only to the fixed OpenRouter endpoint.
- Existing fake, OpenAI, Gemini, and Groq behavior remains supported and
  unchanged.

## Reconsideration triggers

Revisit this decision if OpenRouter removes or materially changes OpenAI
compatibility, or if `OpenRouterLLMClient` needs request/response behavior
that diverges from `GroqLLMClient` enough that subclassing it stops being the
right shape.
