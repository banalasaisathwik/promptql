# Product

PromptQL is an engineering intelligence and investigation system for answering operational questions from approved enterprise evidence.

Its purpose is not merely to generate prose.

The system should help a user answer questions such as:

> Is this pull request ready to merge?

and, in V2:

> Why did this engineering incident happen?

while preserving:

- source provenance
- explicit uncertainty
- deterministic control boundaries
- auditable runtime execution
- validated model output
- safe access to external systems

The long-term product direction is a governed enterprise investigation runtime in which deterministic code handles verifiable state and control, while LLMs are used selectively for tasks such as planning, synthesis, and hypothesis generation.

---

# Product principles

## Evidence before conclusions

Important conclusions must be traceable to source evidence.

The system should be able to answer:

```text
What evidence produced this conclusion?
```

rather than exposing unsupported model prose.

---

## Facts and hypotheses are different

A verified fact and a plausible explanation must never be represented as the same kind of truth.

Example:

```text
Fact:
checkout.py changed in PR #42.

Fact:
the failing stack frame points to checkout.py.

Hypothesis:
the PR #42 change likely caused the incident.
```

The hypothesis may be well grounded without being proven correct.

---

## Unknown is a valid result

When required evidence is unavailable, the system should represent that uncertainty explicitly.

It should not force:

```text
true / false
```

when the correct state is:

```text
unknown
```

or:

```text
insufficient evidence
```

---

## Probabilistic proposal, deterministic control

LLMs may eventually propose:

- plans
- hypotheses
- interpretations

but deterministic application code owns:

- allowed capabilities
- schema validation
- runtime state
- execution budgets
- persistence
- policy checks
- evidence references
- accepted domain state

A model response is never authoritative merely because it successfully matches a JSON schema.

---

## External systems remain untrusted boundaries

GitHub, Jira, observability providers, and future enterprise sources are external systems.

Their responses must be:

```text
retrieve
→ validate
→ normalize
→ use inside the domain
```

Provider-specific schemas should not become core domain models.

---

# Version progression

## V0 — Foundations

V0 established the initial engineering foundation:

- repository structure
- Vite/React/TypeScript frontend
- FastAPI backend
- package-management boundaries
- testing conventions
- documentation practices
- ADRs
- agent-assisted development workflow
- learning-oriented repository conventions

V0 was intentionally not a complete agent runtime.

---

# V1 — Deterministic merge-readiness analysis

V1 answers:

> Is this pull request ready to merge?

The system collects structured GitHub and Jira facts and applies deterministic policy.

The conceptual flow is:

```text
request
   ↓
GitHub facts
   ↓
Jira facts
   ↓
deterministic merge-readiness policy
   ↓
typed MergeReadinessResult
   ↓
optional structured LLM explanation
   ↓
deterministic explanation validator
   ↓
backend-owned rendering
   ↓
API / frontend
```

## V1 product capabilities

V1 currently includes:

- deterministic merge-readiness evaluation
- typed GitHub evidence
- typed Jira evidence
- fake and live connector modes
- independent GitHub/Jira source selection
- explicit missing-information handling
- source provenance
- immutable domain contracts
- typed workflow runs
- ordered runtime steps
- PostgreSQL persistence
- run retrieval by ID
- runtime failure states
- OpenTelemetry tracing
- OpenTelemetry metrics
- Grafana Cloud export
- structured logging
- provider-neutral LLM integration
- structured model output
- deterministic explanation validation
- deterministic backend rendering
- prompt identity/versioning
- model fingerprinting
- provider/token telemetry
- development and holdout eval datasets
- repeated model sampling
- provider reliability measurement
- candidate-quality measurement
- release-threshold reporting

V1 establishes the architectural baseline for V2.

V2 should extend these foundations rather than rebuilding them.

---

# Why V1 is not enough

Merge readiness is mostly a closed deterministic problem.

For example:

```text
PR is draft
→ blocked

required CI failed
→ blocked

required approval missing
→ blocked
```

The system knows which facts are relevant and which workflow steps to execute.

Engineering incident investigation is different.

For an incident such as:

> Checkout started returning HTTP 500 after a deployment. What caused it?

the system may need to investigate several possible relationships:

```text
incident
↓
deployment
↓
commit
↓
pull request
↓
code diff
↓
stack trace
↓
Jira context
```

There may not be a single deterministic rule that directly produces:

```text
root cause = X
```

This creates the need for controlled planning and hypothesis generation.

---

# V2 — Evidence-grounded engineering incident investigation

V2 expands PromptQL from a fixed deterministic workflow into a controlled investigation runtime.

The primary V2 question is:

> Why did this engineering incident happen?

The desired answer should separate:

```text
what we know
what we suspect
what we do not know
what should happen next
```

---

# V2 target experience

A user supplies an incident or investigation goal.

Example:

```text
Checkout is returning HTTP 500 errors.

The errors began shortly after today's deployment.

Investigate the likely cause.
```

The system eventually investigates relevant evidence such as:

- incident metadata
- telemetry
- stack frames
- deployments
- commits
- pull requests
- Git diffs
- Jira issues

and returns a result conceptually similar to:

```text
Investigation Result

Verified facts
---------------
F1. checkout.py changed in PR #42.
F2. commit abc123 was deployed before the incident.
F3. the failing stack frame points to checkout.py:84.

Hypotheses
----------
H1. The checkout.py change likely introduced the failure.
    Supporting evidence: F1, F2, F3
    Grounding: supported
    Confidence: high

Missing information
-------------------
Deployment-to-build metadata is incomplete.

Recommended next action
-----------------------
Verify the null-handling change around checkout.py:84.
```

The system must not turn:

```text
likely cause
```

into:

```text
proven cause
```

without adequate evidence.

---

# V2 target architecture

The planned conceptual flow is:

```text
Investigation Request
        ↓
Investigation Runtime
        ↓
Evidence Collection
        ↓
Deterministic Baseline Investigation
        ↓
Typed Planner
        ↓
Plan Validator
        ↓
Controlled Tool Execution
        ↓
Additional Evidence
        ↓
Hypothesis Generation
        ↓
Evidence / Claim Validation
        ↓
Grounded Investigation Result
```

This section describes the **target V2 direction**.

Individual components become current capabilities only after their milestone has been implemented and validated.

---

# V2.1 — Investigation Domain Model

The first V2 implementation milestone now defines the domain language of an
investigation in `services/api/app/investigations/models.py`.

It establishes typed representations for:

```text
InvestigationRequest

typed investigation facts

Hypothesis

HypothesisConfidence

MissingInformation

RecommendedAction

InvestigationResult
```

The objective is not to implement an agent yet.

The objective is to define:

> What kinds of information can a valid investigation result contain?

The implemented answer is a strict immutable result composed from
machine-readable changed-file, deployment, and stack-frame facts; explicitly
non-authoritative hypotheses; coded missing information; and linked recommended
actions. Cross-references are checked when deterministic application code
assembles the result. V2.2 now supplies the referenced evidence records;
runtime execution and LLM generation remain later milestones.

---

# V2.1 domain rules

## Strongly typed facts

Prefer machine-readable facts over prose-only facts.

Prefer:

```text
ChangedFileFact
path = checkout.py
change_type = modified
```

over relying exclusively on:

```text
"checkout.py changed"
```

Human-readable wording may be generated from structured facts later.

---

## Facts must not become hypotheses

A deterministic fact may support a hypothesis.

It must not automatically prove it.

```text
Changed file
+
stack trace
+
deployment timing

→ supports hypothesis
```

not necessarily:

```text
→ proves root cause
```

---

## Hypothesis grounding is different from correctness

The system may classify a hypothesis as:

```text
supported
weakly supported
contradicted
unsupported
unknown
```

based on available evidence.

This describes grounding.

It does not necessarily describe objective production truth.

True correctness may later be established through:

- known golden eval cases
- engineer confirmation
- remediation outcome
- additional evidence

---

## Investigation result is not runtime state

`InvestigationResult` should describe the investigation conclusion.

Runtime concerns such as:

- run ID
- workflow state
- timestamps
- runtime steps
- retry state
- errors

belong to runtime models.

A future relationship may look like:

```text
InvestigationRun
├── runtime lifecycle
└── result: InvestigationResult
```

similar to V1:

```text
MergeReadinessRun
└── result: MergeReadinessResult
```

---

# V2 planned milestone progression

The current planned progression is:

```text
V2.1
Investigation Domain Model

V2.2
First-class Evidence Model

V2.3
GitHub code/diff evidence (provider capability implemented)

V2.4
IncidentSource abstraction

V2.5
Tool abstraction and registry

V2.6
Deterministic investigation baseline

V2.7
Typed LLM planner

V2.8
Plan validator

V2.9
Agent execution loop

V2.10
Execution budgets

V2.11
Failure taxonomy extension

V2.12
Retries, exponential backoff and jitter

V2.13
Idempotency

V2.14
Crash recovery, checkpoints and resume

V2.15
Cancellation

V2.16
Dynamic replanning

V2.17
Hypothesis generation

V2.18
Evidence-backed claim validation

V2.19
Grounded rendering

V2.20
Component and trajectory evals

V2.21
Agent-level OpenTelemetry/Grafana

V2.22
Replay

V2.23
Queue/workers only if runtime requirements justify them

V2.24
Investigation UI and execution timeline

V2.25
Live verification and V2 release gates
```

This is a roadmap, not a statement that these features currently exist.

---

# Deterministic investigation baseline

Before relying on an LLM planner, V2 should establish a deterministic baseline investigation.

Conceptually:

```text
incident
↓
retrieve incident evidence
↓
identify deployment
↓
identify commit
↓
retrieve PR/diff
↓
retrieve related Jira context
↓
assemble evidence
```

This baseline serves two purposes:

1. establishes a reliable working investigation path
2. gives the future planner something measurable to improve upon

Without a baseline:

```text
agent produced an answer
```

does not demonstrate that agentic planning added value.

---

# Planner product role

The future planner should not directly execute arbitrary actions.

Its role is to propose:

```text
what information should be gathered next
```

The runtime remains responsible for:

- allowed tools
- argument validation
- dependencies
- budgets
- permissions
- execution
- persistence
- failure handling

Conceptually:

```text
LLM planner
   ↓
candidate plan
   ↓
deterministic plan validation
   ↓
runtime executor
```

---

# Evidence product role

V2.2 now defines the domain contract that preserves:

```text
what was observed
where it came from
when it happened
when it was retrieved
what fact or hypothesis references it
```

This enables:

- auditability
- debugging
- grounding
- evaluation
- replay

Evidence should remain distinct from model-generated claims.

The implemented evidence envelope carries stable identity, a logical source,
a typed kind, stable source reference, optional source-event time, required
retrieval time, and one normalized typed content variant. Investigation results
validate fact and hypothesis evidence links. V2.3 now populates commit,
pull-request, changed-file, and bounded diff-hunk evidence through deterministic
fake or validated read-only GitHub HTTP sources. It does not yet derive facts,
choose relevant hunks, expose planner tools, or connect this capability to a V2
runtime/API. Persistence, raw payload snapshots, and evidence UI remain planned.

---

# Evaluation product role

V2 should evaluate more than final-answer correctness.

The system should eventually measure:

```text
planner correctness
tool-selection correctness
tool-argument correctness
evidence retrieval
hypothesis quality
grounding
abstention
final result quality
```

When a final answer is wrong, the system should help identify whether the failure came from:

```text
bad plan
wrong tool
missing evidence
provider failure
reasoning failure
validator failure
```

For hypotheses, explicitly distinguish:

```text
groundedness
```

from:

```text
ground-truth correctness
```

Offline correctness should rely on known reference answers where possible.

Production ground truth may only become available after human investigation or remediation.

---

# Observability product role

V2 should extend the existing OpenTelemetry/Grafana foundation rather than introduce another observability platform without need.

Future investigation traces may include operations such as:

```text
investigation
├── planner
├── plan validation
├── GitHub tool
├── Jira tool
├── telemetry tool
├── replan
├── hypothesis generation
└── claim validation
```

Operational telemetry should remain separate from product-level evidence and runtime events.

---

# Runtime visibility

The product should provide a developer-facing run view so execution can be understood while building the system.

The existing persisted run model remains the initial source of truth.

The progression should be:

```text
current run snapshots
↓
polling-based run dashboard
↓
future durable run events
↓
future SSE live stream
```

Do not introduce event sourcing merely to build the first live dashboard.

---

# V2 scope boundaries

The following are **not required for the initial V2 investigation runtime** unless later requirements demonstrate a concrete need:

- company-wide RAG
- vector database
- embeddings
- BM25
- reranking
- knowledge-graph database
- Slack integration
- write/action tools
- multi-agent swarm
- model-routing platform
- model fallback mesh
- MCP marketplace
- full OAuth/multi-tenancy platform
- Kafka
- Kubernetes
- distributed sharding
- full event-sourcing architecture

These may be valid future directions.

They should not be added merely because they are common in AI systems.

---

# Later product directions

Later versions may extend PromptQL into areas such as:

## Knowledge and context intelligence

Potential capabilities:

- company documentation
- runbooks
- historical incidents
- source-code indexing
- hybrid retrieval
- semantic search
- knowledge graphs

---

## Business analytics

Potential capabilities:

- SQL/data-warehouse investigation
- revenue analysis
- business-metric explanations
- structured causal analysis

---

## Controlled actions

Potential capabilities:

- GitHub comments
- Jira updates
- Slack notifications
- approval workflows
- human-in-the-loop execution

Write tools will require significantly stronger authorization and safety boundaries than read-only investigation tools.

---

## Enterprise platform capabilities

Potential future requirements:

- OAuth
- tenant isolation
- RBAC/ABAC
- per-tenant connector credentials
- provider/model routing
- parallel workflows
- model canaries
- drift detection
- prompt/tool registries
- larger-scale worker execution

These are intentionally outside early V2 scope.

---

# Product success criteria for V2

V2 should be considered successful when it can demonstrate an investigation where:

1. the system starts from a real or controlled engineering incident
2. evidence is collected from approved sources
3. evidence provenance is preserved
4. deterministic facts are separated from hypotheses
5. missing information remains explicit
6. planner-generated actions cannot bypass runtime validation
7. runtime execution is bounded
8. failures are typed and observable
9. model-generated hypotheses are evidence-grounded before exposure
10. the final answer distinguishes known facts from uncertainty
11. the investigation can be evaluated against controlled reference cases
12. the execution path can be inspected and understood
13. existing V1 functionality continues to work

---

# Product non-goals for current V2 work

Current V2 work is not attempting to build:

- a fully autonomous production remediation agent
- a general-purpose coding agent
- an unrestricted tool executor
- a replacement for GitHub/Jira/Grafana
- a generic company search engine
- a multi-agent orchestration platform
- a universal root-cause taxonomy
- a fully production-ready multi-tenant SaaS platform

The objective is narrower:

> Build a reliable, typed, evidence-grounded engineering investigation runtime and learn the architectural principles required to operate it safely.
