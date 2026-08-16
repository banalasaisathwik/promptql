# Execution plan: Groq explanation provider adapter

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-16
- Last updated: 2026-08-16
- Related ADRs: ADR-011, ADR-012, ADR-013, ADR-015, ADR-017
- Related tasks: None

## Objective

Add Groq as an explicit configurable explanation provider behind the existing
`LLMClient` protocol without changing V1 policy, validation, rendering,
persistence, API, frontend, retry, or eval semantics.

## Current behavior and evidence

`LLMSettings.from_environment()` accepts `fake`, `openai`, or `gemini`.
`create_llm_client()` builds the selected adapter, with SDK retries disabled and
Gemini's compatibility URL fixed in code. Every adapter returns
`LLMStructuredResponse`; `MergeReadinessExplanationService` then applies
Pydantic parsing, `StrictMergeReadinessExplanationValidator`, and deterministic
templates. The eval runner uses the same client and keeps provider-attempt
denominators separate from returned-candidate quality denominators.

## Proposed behavior

```text
PROMPTQL_LLM_PROVIDER=groq + GROQ_API_KEY + GROQ_MODEL
-> validated LLMSettings
-> AsyncOpenAI(base_url="https://api.groq.com/openai/v1", max_retries=0)
-> GroqLLMClient
-> strict JSON Schema GeneratedExplanation
-> LLMStructuredResponse
-> existing Pydantic and deterministic validator
-> existing deterministic templates
```

## Scope

- In scope: explicit Groq identity and settings, fixed-endpoint factory wiring,
  one OpenAI-compatible adapter, application-lifecycle close, existing telemetry
  allowlist, eval identity, mocked tests, documentation, ADR, Mermaid, and
  learning evidence.
- Expected systems and files: `services/api/app/config.py`,
  `services/api/app/explanations`, runtime telemetry, provider/eval tests,
  environment and provider docs, architecture/testing docs, and learning docs.

## Non-goals

- No V2 investigation-domain work, model routing, fallback, general retry or
  backoff, key rotation, live paid call, provider-specific eval framework,
  policy change, or public API shape change. The bounded provider vocabulary
  changed in persistence and the frontend response validator so `groq`
  provenance can travel through the existing response shape.

## Acceptance criteria

- [x] Groq configuration requires its own key and model and cannot configure a
      base URL.
- [x] The factory selects `GroqLLMClient` only for explicit `groq` mode and
      constructs `AsyncOpenAI` with the fixed Groq URL and `max_retries=0`.
- [x] Structured claims and token usage normalize into existing provider-neutral
      models; rate limits and malformed responses use the existing taxonomy.
- [x] Deterministic validation/rendering and existing fake/OpenAI/Gemini behavior
      remain unchanged.
- [x] Telemetry and eval reports use bounded `groq` identity and the existing
      safe model fingerprint and attempt/candidate denominators.
- [x] Automated verification makes no external provider call.

## Invariants

- The deterministic policy is the only merge-readiness authority.
- Generated prose is discarded; only exact supported and complete codes reach
  deterministic templates.
- Provider, schema, and validator failures remain distinct.
- Keys, prompts, prose, raw responses, identities, arbitrary model strings, and
  exception text never enter telemetry or public responses.
- One configured call remains one attempt; the SDK and application do not retry.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Missing Groq key/model | Startup or eval preflight raises sanitized configuration error | Correct local secret/model configuration |
| Groq 429/network/auth failure | Existing sanitized provider-failure category | Inspect bounded category; rerun only by explicit operator action |
| Missing/refused/malformed parsed response | Existing invalid-structured-response provider category | Inspect model/schema compatibility without exposing raw response |
| Schema-valid but unsupported/incomplete claims | Existing deterministic validation failure | Evaluate prompt/model quality; policy result remains usable |

## Security

`GROQ_API_KEY` is passed only to the in-code
`https://api.groq.com/openai/v1` endpoint. No environment-controlled Groq base
URL exists. The adapter sends only the minimized decision/reason/action model
and never logs or persists secrets, provider payloads, or generated prose.

## Observability

Reuse the existing explanation span, duration/token metrics, safe model
fingerprint, prompt identity, and sanitized failure event. Add only `groq` to
the closed provider vocabulary; never use the configured model as a metric
label.

## Milestones

1. Implement and focus-test configuration, factory, adapter, telemetry, and eval
   identity without network access.
2. Synchronize documentation, run the complete backend suite and static checks,
   review the final diff/security boundary, and close this plan.

## Validation strategy

Run Groq/config/provider/explanation/eval tests first, then all provider and eval
tests, complete backend `unittest` discovery, Python compilation, and
`git diff --check`. Report PostgreSQL credential-gated skips exactly. Do not run
a real-provider eval or smoke call.

## Progress

- [x] 2026-08-16: Inspected current provider, validation, telemetry, eval, tests,
      dirty worktree, architecture, ADRs, and official Groq documentation.
- [x] 2026-08-16: Implemented the adapter, bounded identity propagation,
      persistence migration, frontend validation, documentation, and mocked
      verification. The complete backend suite passed with PostgreSQL-only
      tests skipped because `TEST_DATABASE_URL` was absent; frontend tests,
      lint, and build passed.

## Decisions and discoveries

- Reuse the installed OpenAI Python SDK and Groq's fixed OpenAI-compatible
  endpoint; no dependency is added.
- Use Chat Completions Pydantic parsing because Groq documents strict JSON
  Schema support there and the installed SDK converts the Pydantic model into a
  strict schema.
- Recommend `openai/gpt-oss-20b` initially for the bounded V1 workload; retain
  required `GROQ_MODEL` configuration and evaluate 120B only if model-quality
  evidence warrants its higher latency and cost.

## Risks and open questions

- Mocked tests prove request construction and normalization, not live Groq
  credentials, quota, model availability, or end-to-end schema behavior. Those
  remain an explicitly authorized future live gate.

## Completion

Completed on 2026-08-16. Groq is available as an explicit V1 explanation
provider through the fixed compatibility endpoint. Automated verification made
zero provider calls. Live Groq schema behavior and the PostgreSQL migration
round trip remain deployment gates because credentials and a test database were
intentionally unavailable for this task.
