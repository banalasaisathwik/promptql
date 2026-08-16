# ADR-017: Groq through the OpenAI-compatible explanation boundary

- Status: Accepted
- Date: 2026-08-16
- Owners: Repository owner
- Extends: ADR-012 and ADR-013 with a third real provider
- Superseded by: None

## Context

PromptQL already isolates fake, OpenAI, and Gemini generation behind
`LLMClient`, then treats generated data as untrusted until Pydantic and the
deterministic merge-readiness validator accept it. Groq exposes an
OpenAI-compatible API and supports strict JSON Schema output on GPT-OSS 20B and
120B. Adding Groq must not confuse API compatibility with provider identity or
weaken the existing policy authority, validation, retry, telemetry, or eval
boundaries.

## Decision

- Add explicit `groq` provider identity and `GROQ_API_KEY`/`GROQ_MODEL`
  configuration. Both values are required when Groq is selected.
- Reuse the installed OpenAI Python SDK with the fixed
  `https://api.groq.com/openai/v1` base URL and `max_retries=0`. Do not add an
  environment-configurable Groq base URL or a Groq SDK dependency.
- Isolate Groq request/response and SDK error behavior in `GroqLLMClient`; return
  only the existing provider-neutral `LLMStructuredResponse`.
- Use Chat Completions Pydantic parsing so the SDK sends a strict JSON Schema for
  `GeneratedExplanation`. Pydantic and the deterministic validator remain the
  application trust boundaries even when constrained decoding is available.
- Recommend `openai/gpt-oss-20b` for the initial bounded V1 explanation workload.
  Keep the model required in configuration; use controlled eval evidence before
  choosing the more capable, slower, and more expensive 120B alternative.
- Extend existing safe telemetry and eval identity with the bounded `groq`
  value. Do not add model labels, new denominators, automatic retries, or a
  Groq-specific eval path.
- Extend the existing durable `explanation_source` vocabulary with `groq`
  through migration `20260816_0003`; preserve the column and public run schema.

## Alternatives considered

### Masquerade Groq as OpenAI with a configurable base URL

This reduces adapter code but mislabels credentials, failures, telemetry, and
eval reports. A configurable URL also creates a credential-forwarding risk.

### Add the official Groq SDK

The native SDK could express the same API, but the repository already owns a
compatible and tested OpenAI SDK dependency. A second production dependency
would expand maintenance and supply-chain surface without improving the domain
boundary for this operation.

### Use Groq's beta Responses API

It more closely resembles the OpenAI adapter, but Chat Completions has the
documented strict JSON Schema path needed here and avoids coupling the initial
adapter to a beta endpoint. Both choices stay behind `LLMClient`; the operation
can change later without changing domain models.

### Hard-code GPT-OSS 120B

The larger model may improve difficult reasoning, but this input is a small
closed claim-selection task followed by deterministic validation. Hard-coding
would prevent controlled model evaluation and impose higher latency and token
cost without repository evidence that it improves V1 outcomes.

## Consequences

Groq becomes independently configurable and observable without a dependency,
public schema, policy, service, validator, renderer, or frontend change. The
existing persistence constraint gains one bounded value. The adapter duplicates
a small amount of provider-specific SDK error mapping so network and response
behavior stay isolated and testable.

Downgrade restores the old three-provider constraint. If durable Groq rows
exist, PostgreSQL rejects that downgrade transaction rather than silently
discarding or relabeling their provenance; an operator must resolve those rows
deliberately before retrying.

API compatibility does not imply operational equivalence. Groq credentials,
quota, model availability, token reporting, and error behavior remain Groq
concerns. Mocked tests can prove the local contract, but an explicitly approved
live smoke/eval remains necessary before claiming live-provider verification.

## Invariants

- The deterministic policy result remains the only readiness authority.
- Groq receives only minimized stable policy codes and a fixed instruction.
- `GROQ_API_KEY` is sent only to the fixed Groq endpoint.
- Generated prose and raw provider data never reach users, persistence, logs,
  traces, metrics, or eval reports.
- SDK retries remain disabled; a 429 is one visible provider failure attempt.
- Provider, schema, and deterministic-validation failures remain distinct.
- Existing fake, OpenAI, and Gemini behavior remains supported.

## Reconsideration triggers

Revisit this decision if Groq removes or materially changes OpenAI
compatibility, strict schema support changes, live eval evidence favors another
model, a native Groq feature becomes necessary, or V2 introduces explicit model
routing/retry policies.
