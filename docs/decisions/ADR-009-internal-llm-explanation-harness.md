# ADR-009: Internal provider-neutral LLM explanation harness

- Status: Partially superseded by ADR-010
- Date: 2026-08-09
- Owners: Repository owner
- Supersedes: None
- Superseded by: ADR-010 for semantic validation and API exposure

## Context

The deterministic merge-readiness policy produces authoritative typed results,
but no internal boundary exists for generating user-friendly wording. The
repository has no selected real model provider, provider SDK, prompt framework,
semantic explanation validator, or safe public explanation contract.

## Decision drivers

- Preserve the deterministic policy as the only readiness authority
- Minimize data before it crosses a future model-provider boundary
- Test success and failure without network access or randomness
- Reject malformed output without changing persisted runtime state
- Reuse bounded OpenTelemetry conventions without prompts or outputs
- Avoid selecting a provider or adding a production dependency silently

## Options considered

### Add explanation generation to the workflow now

This would make every completed policy result flow immediately to a model, but
there is no validated response or persistence field for the output. It would
also mix probabilistic provider failure into established runtime semantics.

### Implement a concrete provider SDK first

This would enable real calls, but the repository has not selected a provider.
It would introduce credential, dependency, cost, rate-limit, and operational
decisions outside this bounded milestone.

### Build an internal injected harness with a deterministic fake

This establishes the trust boundary, contracts, failure taxonomy, and telemetry
without exposing unvalidated prose or coupling the design to one vendor.

## Repository owner reasoning

The approved milestone requires a provider-neutral `LLMClient`, deterministic
fake, structured Pydantic result, strict prompt-data minimization, safe
telemetry, and no API/persistence exposure before a deterministic explanation
validator exists.

## Reasoning review

This order isolates the highest-risk boundary—what reaches and returns from a
model—before adding credentials or user-visible behavior. A workflow-integrated
adapter would become preferable only after semantic validation and explicit
failure/output ownership are designed.

## Decision

- **Decision:** Add an internal `MergeReadinessExplanationService` around an
  injected provider-neutral `LLMClient.generate_structured()` contract.
- **Reason:** The service can minimize input, validate output shape, enforce the
  unchanged decision, and sanitize failure independently of policy/runtime.
- **Alternative considered:** Integrate generation into the workflow or choose
  a real provider immediately.
- **Tradeoff:** The harness is testable and secure by construction but cannot
  yet produce a user-visible explanation.
- The only default implementation is deterministic `FakeLLMClient`.
- Model input contains only decision, primary reason code, blocker reason
  codes, missing-information reason codes, and pending-action codes.
- Pydantic shape validation and exact-decision equality are enforced now.
  Semantic grounding of summary/reasons/actions is the next milestone.
- `create_app()` owns the default or explicitly injected client. The current
  workflow and routes do not invoke the service.
- One safe span and bounded duration/token metrics are recorded. Prompts,
  outputs, identities, provider/model names, and raw errors are excluded.

## Consequences

- Tests can exercise model boundaries without an external service.
- Provider and malformed-output failures are typed and sanitized.
- Completed policy results and stored runs remain unchanged on any explanation
  failure because the harness is not part of runtime execution.
- There is no dependency, lockfile, route, response-model, database, migration,
  runtime-step, connector, or frontend change.
- The fake's token counts are deterministic test metadata, not tokenizer claims
  about a future provider.

## Invariants

- An LLM never calculates, changes, or overrides merge readiness.
- Connector facts and evidence values never enter LLM input.
- Prompts and outputs are never persisted or logged.
- No explanation is exposed before semantic validation is implemented.
- Telemetry failure never changes explanation or policy behavior.

## Validation

Focused and complete command results are recorded in the completed execution
plan and learning log after verification.

## Reconsideration triggers

Revisit this decision when selecting a real provider, defining prompt versions,
adding deterministic semantic validation, choosing whether explanation failure
affects a later workflow step, or exposing explanations through an authorized
API and persistence contract.
