# ADR-029: Versioned investigation component and trajectory evals

- Status: Accepted
- Date: 2026-08-21

## Context

V2 uses several probabilistic proposals inside a deterministic runtime. The V1
explanation harness evaluates one generated explanation, so extending its case
and observation models would couple unrelated workflows and still fail to
measure investigation trajectories. V2 needs to attribute failures to provider
execution, structured parsing, individual reasoning components, deterministic
grounding, or the controlled runtime.

## Options considered

### Option A: Extend the V1 explanation observation and graders

This reuses more files, but one observation would need unrelated optional fields
for planner, hypothesis, diagnosis, and multi-round state. It would weaken the
meaning of both V1 and V2 reports.

### Option B: Add V2-specific contracts and execution under the existing eval package

The V2 harness can reuse shared provider identity, rate, latency, token, safety,
and paid-call controls while owning investigation cases and graders. It can call
the real production components and workflow with deterministic fake connectors.

### Option C: Evaluate only final rendered answers

This is simpler, but a failure cannot be attributed to planning, retrieval,
grounding, diagnosis, or runtime control. A plausible final sentence could also
hide an invalid trajectory.

## Decision

Choose Option B. Versioned development and holdout cases contain a typed
`InvestigationRequest` plus stable expected Evidence, Fact, hypothesis, code
category, and recommendation identifiers. Every sample evaluates planner
validity/usefulness, deterministic Fact derivation, hypothesis generation and
validation, code diagnosis, recommendations, and adversarial rejection. The
same sample also runs the production adaptive workflow and grades its trajectory.

Trajectory grading checks allowed tools, validated plans, global budget and
round limits, relevant Evidence discovery, grounded Facts/hypotheses/findings,
grounded recommendations, and sensible termination. It compares Evidence and
Fact recall with the deterministic baseline, but does not require an exact tool
order because multiple valid plans may retrieve the same required evidence.

Provider execution and schema validity use separate denominators from component
and trajectory quality. Repeated samples apply only to probabilistic calls. The
normal report persists aggregate identifiers, rates, latency, and token totals;
it omits questions, source payloads, code, prompts, model output, credentials,
and exception text. Cost stays unknown without versioned pricing.

## Consequences

- A failing report identifies operational, schema, component, or trajectory
  failure instead of collapsing them into one accuracy value.
- Production validators define grounding, reducing grader/runtime semantic drift.
- Development and holdout workflows are operationally separate, but the first
  catalog has one checkout fixture expressed through two questions. It proves
  harness behavior and guards the supported fixture; it is not broad incident
  quality evidence.
- One default case with three samples may make at most 24 provider calls: three
  isolated component calls plus up to five workflow calls per sample. Preflight
  reports this bound without constructing a client or contacting a provider.
- No LLM judge, hosted eval service, exact-plan ordering, raw-output artifact,
  automatic retries, or production-traffic collection is introduced.

## Security and evaluation boundaries

External Evidence remains untrusted input. Only validated model proposals can
enter the observed trajectory. Unsupported Fact and Evidence references are
deliberately injected and must be rejected by production validators. Fake runs
are credential-free; real runs require explicit paid-call acknowledgement.

Grounding proves that a claim is supported by the available structured fixture.
Reference matching measures agreement with the case label. Neither proves the
true production root cause, which still requires human or operational ground
truth.

## Validation

Focused tests cover versioned split separation, successful component and
trajectory grading, provider/schema failure attribution, repeated independent
samples and pacing, bounded maximum-call accounting, and aggregate-only report
artifacts. Three-sample fake development and holdout runs exercise the production
components and complete adaptive workflow without network access.

## Reconsideration triggers

Expand the catalog when new deterministic connector fixtures represent distinct
incident families. Consider a hosted service or supplemental human/LLM judging
only when case volume makes local reports operationally insufficient, and keep
those judgments non-authoritative.
