# ADR-013: Gemini through the OpenAI-compatible explanation boundary

- Status: Accepted
- Date: 2026-08-10
- Owners: Repository owner
- Extends: ADR-012 with a second real provider
- Partially superseded by: ADR-014 for the Gemini Structured Output schema

## Context

The first real adapter used the OpenAI SDK's native Responses API. Configuring
that adapter with `gemini-2.5-flash` still sent the request to OpenAI's default
endpoint, so the provider failed before PromptQL could validate an explanation.
Google documents an OpenAI-compatible endpoint, but its structured-output path
uses Chat Completions rather than OpenAI's Responses operation.

## Decision

- Add explicit `gemini` selection and `GEMINI_*` settings while retaining
  credential-free `fake` as the default and native `openai` as a separate mode.
- Reuse the installed `AsyncOpenAI` SDK with retries disabled and the fixed
  `https://generativelanguage.googleapis.com/v1beta/openai/` base URL.
- Use `beta.chat.completions.parse(response_format=GeneratedExplanation)` for Gemini
  and keep `responses.parse(text_format=GeneratedExplanation, store=False)` for
  OpenAI.
- Convert Gemini token field names into the existing provider-neutral envelope
  and reuse the sanitized failure taxonomy, deterministic validator, templates,
  telemetry contract, API shape, and UI.
- Never accept an arbitrary LLM base URL from the environment.

## Alternatives considered

### Reuse `openai` mode with an `OPENAI_BASE_URL`

This is smaller, but it mislabels Gemini traffic and credentials. An arbitrary
URL also creates a credential-forwarding risk if configuration is incorrect or
compromised.

### Infer the provider from a model prefix

Automatic inference hides an important network and credential boundary. A
mistyped model could send a key to the wrong provider, and telemetry would be
ambiguous.

### Replace the OpenAI adapter with Gemini

This would remove a working provider instead of extending the provider-neutral
contract and would make later provider selection harder to reason about.

## Consequences

Gemini can now use the OpenAI SDK without pretending to be OpenAI. There is no
new dependency, public API change, migration, policy change, or frontend change.
The application owns two provider-specific API operations because Google's
compatibility surface does not document the Responses operation used by OpenAI.

Provider credentials, model access, quota, and availability can still fail at
runtime. Such failures remain sanitized and cannot alter the completed policy
run. Automated tests use SDK doubles and make no external provider requests.

## Invariants

- The deterministic policy result remains the only readiness authority.
- Generated prose remains untrusted and is discarded before rendering.
- `GEMINI_API_KEY` is sent only to Google's fixed compatibility endpoint.
- Provider failures never fall back, expose raw details, or mutate persistence.
- Provider names remain closed, low-cardinality telemetry values.

## Reconsideration triggers

Revisit this decision if Google changes or removes its compatibility contract,
if a native Gemini SDK becomes necessary, or if tenant-specific credentials,
fallback, persistence, or provider routing are introduced.
