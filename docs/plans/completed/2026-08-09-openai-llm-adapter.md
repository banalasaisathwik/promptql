# Execution plan: OpenAI merge-readiness explanation adapter

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-09
- Last updated: 2026-08-09
- Related ADRs: ADR-009, ADR-010, ADR-011, ADR-012
- Related tasks: None

## Objective

Add an optional real OpenAI Responses API implementation of the existing
provider-neutral `LLMClient` while keeping the fake as the default and keeping
the deterministic policy result, validator, templates, API, UI, and persisted
runtime run authoritative and unchanged.

## Current behavior and evidence

`create_app()` always selects `FakeLLMClient` unless a test injects another
client. `MergeReadinessExplanationService` sends a minimized typed policy view
through `LLMClient`, validates generated reason/action codes against the full
policy result, discards generated prose, and renders approved templates.
Provider failures become the existing sanitized `explanation_error` and never
mutate the completed runtime run.

## Proposed behavior

`PROMPTQL_LLM_PROVIDER=fake` keeps the current path. OpenAI mode validates its
API key, model, timeout, and output-token limit during application assembly,
then injects `OpenAILLMClient`. The adapter asynchronously calls the Responses
API with Structured Outputs, `store=False`, no tools or response chaining, and
SDK retries disabled. It returns only the existing provider-neutral envelope.
Provider-specific failures are converted to stable sanitized categories before
the service handles them.

## Scope

- In scope: official OpenAI Python SDK, provider settings and application
  selection, async Responses API adapter, sanitized provider taxonomy, bounded
  provider/token telemetry, mocked tests, configuration/example documentation,
  ADR/architecture/testing/learning records, and the ignored Mermaid flow.
- Expected systems and files: `services/api/pyproject.toml`, `uv.lock`,
  `.env.example`, `app/config.py`, `app/main.py`, `app/explanations`,
  `app/observability`, backend tests, and documentation.

## Non-goals

- No retries, provider fallback, streaming, additional providers, tools,
  response chaining, prompt/output persistence, generated-prose exposure,
  route/frontend/database/policy changes, caching, or live API execution.

## Acceptance criteria

- [x] Fake is the credential-free default and OpenAI mode fails clearly without
  a key or model.
- [x] The adapter uses typed Responses Structured Outputs, `store=False`, the
  configured model/timeout/token bound, and zero SDK retries.
- [x] Only minimized policy categories cross the provider boundary.
- [x] Provider failures are sanitized into the approved closed taxonomy.
- [x] Real-adapter output passes through the unchanged deterministic validator.
- [x] Telemetry records only bounded provider/operation/outcome/token data.
- [x] Automated tests make no external requests and existing API/UI behavior
  remains unchanged.

## Invariants

- The deterministic policy result is the only merge-readiness authority.
- Generated prose and raw provider failures never reach API responses,
  persistence, logs, spans, or metrics.
- OpenAI failure never falls back to fake and never changes the stored run.
- Provider selection occurs only at application assembly.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Invalid provider configuration | Startup fails with a secret-free message | Correct environment values or select fake |
| Provider authentication/rate/network failure | Existing sanitized explanation error; policy response remains usable | Correct provider access or retry a later request |
| Refusal or invalid structured response | Existing sanitized explanation error | Review bounded prompt/schema offline |
| Telemetry export failure | Explanation behavior remains unchanged | Inspect safe telemetry warning |

## Security

The API key is stripped, excluded from dataclass representation, and passed
only to the SDK client. The adapter serializes only
`MergeReadinessExplanationInput`; repository identity, connector payloads,
URLs, database values, headers, provider output, and exception details remain
outside observable and durable boundaries.

## Observability

Use closed provider/result/failure categories, operation name, latency, and
provider-reported input/output/total token counts. Do not record the configured
model identifier because it is deployment-controlled and unbounded. Do not
record prompts, outputs, request IDs, or exception text.

## Milestones

1. Add the SDK/configuration/adapter and focused mocked tests.
2. Integrate application selection and telemetry, then complete full
   backend/frontend validation and documentation.

## Validation strategy

Run focused adapter/config/explanation tests, complete backend discovery,
Python compilation, existing frontend tests/lint/build, `git diff --check`, and
a final secret/network/API-schema review. Do not run a live provider request.

## Progress

- [x] 2026-08-09: Inspected repository instructions, current explanation
  pipeline, configuration, application assembly, telemetry, tests, ADRs, and
  official OpenAI Structured Outputs guidance.
- [x] 2026-08-09: Implemented and verified the bounded adapter milestone.

## Decisions and discoveries

The official SDK is isolated behind `LLMClient`. Structured Outputs provides
shape validation; the existing deterministic validator remains responsible for
semantic grounding. Monetary cost is not calculated because pricing changes
by model and time; token counts provide the stable measurement input.

## Risks and open questions

- A configured model may not support the requested Structured Output schema;
  this fails as a sanitized provider/invalid-response error and must be covered
  by a manual smoke test for the chosen deployment model.

## Completion

Implemented the official async SDK adapter, explicit fake/OpenAI configuration,
one-attempt Responses Structured Output request, sanitized failure taxonomy,
and bounded provider/token telemetry without changing policy, validator, API,
frontend, runtime, or persistence schemas. The focused suite passed 46 tests.
Complete backend discovery ran 151 tests: 147 passed and four guarded
PostgreSQL tests skipped. Frontend tests, lint, type checking, build, and Python
compilation passed. Automated tests used injected SDK clients and made no
external provider request.
