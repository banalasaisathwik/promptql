# Execution plan: Internal merge-readiness LLM explanation harness

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-09
- Last updated: 2026-08-09
- Related ADRs: ADR-009
- Related tasks: None

## Objective

Add a provider-neutral, internal harness that can turn an authoritative typed
merge-readiness policy result into a structured explanation without changing
policy, runtime, persistence, API, or frontend semantics.

## Current behavior and evidence

`MergeReadinessWorkflowService` persists a completed run only after
`evaluate_merge_readiness()` returns a typed result. No LLM client, explanation
model, prompt boundary, or model-call telemetry exists. The API returns only
the persisted deterministic result and supporting facts.

## Proposed behavior

An independently invoked explanation service will minimize a completed policy
result into stable codes, call an injected `LLMClient.generate_structured()`,
validate the returned Pydantic shape and exact decision, and return an internal
typed explanation. `create_app()` will own a deterministic fake by default or
an explicitly injected client. The workflow and public API will not call it.

## Scope

- In scope: typed input/output models, client protocol, deterministic fake,
  sanitized errors, explanation service, application-boundary injection, one
  bounded span, duration and token metrics, tests, ADR, architecture/testing
  documentation, and learning evidence.
- Expected systems and files: `services/api/app/explanations`, application
  assembly, runtime telemetry, backend unit tests, and documentation.

## Non-goals

- Real model provider, semantic explanation validator, workflow step, API or
  frontend exposure, persistence, retries, fallbacks, queues, or migrations.

## Acceptance criteria

- [x] Ready, blocked, and unknown results produce typed explanations.
- [x] The explanation decision must equal the authoritative policy decision.
- [x] Only approved stable policy fields reach the injected client.
- [x] Malformed output and provider failures become typed sanitized errors.
- [x] Identical fake inputs produce identical outputs.
- [x] Model-call telemetry contains only allowlisted bounded attributes/labels.
- [x] Existing backend behavior and tests remain unchanged.

## Invariants

- The harness never computes, mutates, persists, or exposes a policy decision.
- Raw connector/provider content, identities, secrets, prompts, outputs, and
  exception messages never enter persistence, logs, spans, or metric labels.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Provider raises | Sanitized `provider_failure` explanation error | Policy result and stored run remain unchanged; caller may retry later |
| Output is malformed or decision differs | Sanitized `invalid_output` explanation error | Reject output; do not expose or persist it |
| Telemetry recording fails | Explanation behavior remains unchanged | Existing telemetry isolation emits no model data |

## Security

The service builds its own closed input model from policy enums. It never
accepts connector payloads, repository fields, Jira content, credentials,
database values, prompts supplied by users, or arbitrary exception messages.

## Observability

Record one internal span plus duration and optional token measurements. Only
fixed operation, result, failure, and token-type vocabularies are allowed.
Prompts, outputs, model/provider names, identities, and raw errors are excluded.

## Milestones

1. Implement and focus-test typed minimization, client/fake, validation, errors,
   app injection, and safe telemetry.
2. Run full backend verification, review boundaries, synchronize docs, and move
   this plan to completed with exact results.

## Validation strategy

Run the focused explanation test module, configured backend static checks if
present, full `unittest` discovery, `compileall`, and `git diff --check`.
PostgreSQL tests remain credential-gated and must be reported separately.

## Progress

- [x] 2026-08-09: Inspected current policy, workflow, runtime, persistence,
  application assembly, telemetry, tests, and documentation.
- [x] 2026-08-09: Implemented and validated the internal harness.

## Decisions and discoveries

The repository has no real LLM provider or provider SDK. ADR-009 will record
the approved internal provider-neutral boundary and deferred integration.

## Risks and open questions

- Structured shape validation does not prove that explanation prose is
  evidence-grounded. API exposure remains blocked on the next deterministic
  explanation-validator milestone.

## Completion

The harness, deterministic fake, application injection, bounded telemetry,
tests, ADR, architecture/testing documentation, local Mermaid flow, and
learning entry are complete. Focused explanation tests passed 8 tests; focused
observability regression passed 13 tests; complete backend discovery ran 122
tests successfully with four PostgreSQL credential-gated skips; `compileall`
and `git diff --check` passed. No formatter, linter, or static type checker is
configured for the backend. No automated test contacted a model provider.
