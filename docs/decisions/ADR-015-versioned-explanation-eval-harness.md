# ADR-015: Versioned local explanation evaluation harness

- Status: Accepted
- Date: 2026-08-11
- Owners: Repository owner
- Extends: ADR-011 through ADR-014
- Superseded by: None

## Context

The controlled Stage 1 observation used eleven deterministic cases and one
Gemini sample per case. Seven provider calls returned exact validated claims;
four failed with the sanitized `rate_limit` category. That result demonstrated
why candidate quality and provider reliability need separate denominators. It
did not establish repeatability, an untouched holdout result, a release
threshold, or a compatible baseline.

## Decision

- Identify the logical prompt as `merge-readiness-explanation` version `v1`.
- Formalize the eleven inspected cases as
  `merge-readiness-development-v1` and keep six previously unexecuted
  variations in `merge-readiness-holdout-v1`.
- Derive every expected decision/reason/action set through the production
  policy and shared `required_explanation_claims()` function.
- Default both datasets to three samples per case. Execute serially with a
  configurable one-second delay between calls and no automatic retry.
- Record every planned call as one outcome. Keep attempt/provider metrics
  separate from metrics whose denominator is only returned candidates.
- Grade decision equality, exact reason/action sets, micro precision/recall,
  production-validator acceptance, candidate quality, and attempt success.
- Treat duplicate codes with set semantics for precision/recall while retaining
  the production validator's duplicate rejection.
- Write each sanitized observation immediately to JSONL and write a completed
  typed JSON report before returning a threshold-related nonzero exit code.
- Show only aggregate normal holdout output. `--debug-holdout-details`
  deliberately spends the holdout by exposing its per-case claims locally.
- Serialize completed-run baselines and reject comparisons when prompt,
  dataset, provider, model, sample count, or model settings are incompatible.
- Use versioned V1 quality thresholds and independently require zero provider
  failures for the initial operational threshold. Report both outcomes and the
  combined release result.

## Alternatives considered

### Count provider failures as malformed model output

This would lower schema-quality metrics even though no candidate existed. It
would hide whether the problem belongs to provider availability or generated
content.

### Retry rate limits automatically

Retries can improve operational completion, but each retry is another model
attempt. Hidden retries change sample counts, cost, and probability estimates.
Future retry policy must model those attempts explicitly.

### Print full holdout differences by default

That would simplify debugging but immediately turns holdout cases into
development data. Aggregate-only output preserves their intended role until an
operator deliberately opts into inspection.

### Adopt a hosted eval service

Hosted systems can add orchestration and visualization, but this milestone
needs deterministic repository-owned policy labels, provider-neutral adapters,
and local security controls. A hosted service would add coupling without
replacing those requirements.

## Consequences

The repository can measure model quality and provider operation honestly across
repeated samples and compare compatible completed runs. A three-sample default
is still a small experiment, not a statistically strong reliability estimate.
The one-second delay reduces request bursts but increases wall-clock duration.
The initial zero-provider-failure operational rule may be too strict for some
providers and should be reconsidered only with measured baseline evidence.

## Invariants

- The deterministic policy remains the only readiness authority.
- Expected claims are never manually duplicated in dataset definitions.
- One planned sample produces exactly one observation; pacing never retries.
- Provider failures remain visible in attempt metrics and are excluded from
  candidate-quality denominators.
- Prompts, prose, credentials, connector facts/identities, raw responses,
  exception text, and pricing estimates without versioned pricing configuration
  never enter eval artifacts.
- Automated tests use only fake or injected clients and never contact a model
  provider.
- The public API, frontend, runtime, persistence, and production telemetry
  contracts remain unchanged.

## Reconsideration triggers

Revisit this decision when sample sizes need statistical confidence intervals,
pricing configuration is versioned, retries are modeled explicitly, holdouts
are rotated, a hosted eval service is evaluated, or production-traffic examples
become eligible under an approved privacy and retention policy.
