# ADR-012: OpenAI Structured Output explanation adapter

- Status: Accepted
- Date: 2026-08-09
- Owners: Repository owner
- Supersedes: ADR-009 only for the fake-only provider limitation
- Superseded by: None

## Context

ADR-009 created a provider-neutral `LLMClient`; ADR-011 made generated claims
safe to expose by grounding decision/reason/action codes in the deterministic
policy and discarding generated prose. The application still had only a fake
implementation. A real provider must preserve those trust boundaries while
adding network, credential, latency, cost, and provider-failure behavior.

## Decision

- Add the official OpenAI Python SDK as a production dependency isolated behind
  `OpenAILLMClient` and the existing `LLMClient` protocol.
- Select `fake` or `openai` only during FastAPI application assembly. Fake
  remains the local and automated-test default; OpenAI mode requires an API key
  and explicit model.
- Use the async Responses API `parse()` operation with
  `GeneratedExplanation` as the Structured Output schema, `store=False`, a
  configured timeout/output-token limit, and SDK retries disabled.
- Send only the existing minimized policy projection plus fixed instructions.
  Do not send connector payloads, repository identity, Jira values, URLs,
  database information, secrets, tools, or conversation state.
- Normalize SDK failures into a closed internal taxonomy. Public responses keep
  the existing generic `explanation_error`; no raw provider detail crosses the
  API, persistence, log, trace, or metric boundary.
- Preserve `StrictMergeReadinessExplanationValidator` and deterministic
  template rendering. The provider cannot change the policy decision and its
  generated prose is discarded.
- Record bounded provider, operation, result/failure, latency, and provider-
  reported token data. Do not record model identifiers or calculate monetary
  cost in application code.

## Alternatives considered

### Call the Responses API directly with `httpx`

This avoids the SDK dependency but requires application-owned authentication,
request/response compatibility, Structured Output schema conversion, parsing,
and provider error mapping. That duplicates maintained provider behavior and
increases drift risk.

### Use free-form JSON generation

The application could parse JSON manually, but JSON validity does not enforce
the closed Pydantic schema. Structured Outputs narrows malformed-output risk;
the deterministic validator still handles semantic support and completeness.

### Add fallback from OpenAI to the fake

Fallback would hide a production provider outage and present synthetic output
as if the selected provider succeeded. OpenAI failures remain explicit and
sanitized instead.

### Persist generated explanations now

Persisting would avoid repeated model calls during GET, but requires a database
schema, versioning, retention, and regeneration policy outside this bounded
milestone. Read-time generation is retained and documented as a limitation.

## Consequences

OpenAI mode can produce grounded explanations through the existing API/UI
without changing policy, persistence, or public schemas. Network calls add
latency, provider availability, and token cost. Because explanations remain
read-time enrichment, both POST and later GET requests can invoke the provider.
The final visible wording remains deterministic because only validated codes
reach backend templates.

The official SDK and its transitive dependencies increase the backend runtime
and supply-chain surface. Vendor coupling is confined to configuration,
factory, and adapter modules; the service, validator, API, UI, and runtime
remain provider-neutral.

## Invariants

- The deterministic policy result is the only readiness authority.
- OpenAI receives only the minimized decision/reason/action contract.
- Generated prose and raw provider data never reach users or durable storage.
- OpenAI failure never silently selects the fake or changes the completed run.
- Automated tests inject the SDK boundary and make no external provider calls.
- Telemetry uses closed low-cardinality categories and never contains secrets,
  prompts, output, exception text, request IDs, or configured model IDs.

## Reconsideration triggers

Revisit this decision when adding explanation persistence, prompt/model
versioning, offline evals, provider fallback, application retries, another real
provider, tenant-specific credentials, or monetary cost attribution.
