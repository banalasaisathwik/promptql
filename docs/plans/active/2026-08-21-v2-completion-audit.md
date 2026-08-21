# Execution plan: V2 completion audit and release gate

- Status: Active
- Owner: Repository owner
- Created: 2026-08-21
- Last updated: 2026-08-21
- Related ADRs: ADR-018, ADR-019, ADR-020, ADR-021, ADR-023, ADR-024, ADR-025
- Related tasks: PromptQL V2 autonomous completion run

## Objective

Take the repository from its merged V2.19 baseline to a genuinely complete,
live-verified V2 investigation product. Audit implementation truth first, close
only demonstrated gaps, preserve deterministic authority over model proposals,
and retain exact release evidence.

## Current behavior and evidence

The current product already routes `POST /v1/investigations` through a persisted
`InvestigationRun`, `AdaptiveInvestigationRuntime`, the typed planner,
`PlanValidator`, `AgentExecutor`, normalized Evidence, deterministic Fact
derivation, bounded replanning, typed hypothesis generation, deterministic
hypothesis validation, grounded rendering, PostgreSQL snapshot persistence, and
frontend polling.

Baseline validation on 2026-08-21:

- Backend discovery: 374 passed; six PostgreSQL tests skipped without process
  environment configuration.
- Frontend: 38 passed; Oxlint and the production build passed.
- Python `compileall` and `git diff --check` passed.
- OpenRouter `openai/gpt-oss-120b`: typed schema, routed planner, and hypothesis
  diagnostics passed live. The exact-word plain diagnostic rejected a
  semantically different response and needs a more structural assertion.
- The configured dedicated PostgreSQL URL reached Neon but authentication was
  rejected, so live database persistence is currently an external credential
  gate.

The audit also found that the default fake investigation API can complete after
the fake typed client rejects both planning and hypothesis generation. Existing
tests therefore prove the HTTP envelope but do not prove the advertised offline
trajectory. Code diagnosis, grounded remediation, V2-specific telemetry,
Langfuse configuration/instrumentation, and V2 agent evals are absent or only
configuration-ready.

## Initial capability audit

| Capability | Initial status | Evidence or gap |
| --- | --- | --- |
| A. Domain / epistemic model | Partial | Typed request, Evidence, Facts, missing information, hypotheses, and legacy actions exist; no validated code finding. |
| B. Normalized evidence | Done | Typed incident, deployment, telemetry, stack, PR, file, hunk, commit, and Jira evidence with provenance. |
| C. Tool system | Done | Typed, read-only registry/invoker/adapters and sanitized failures are wired into the live workflow. |
| D. Fact derivation | Done | Full-set deterministic derivation and ID dedupe cover the supported product relationships. |
| E. Missing information | Partial | Source and failure-location gaps propagate; final dedupe and persistence context need review. |
| F. Typed planner | Done | Provider-neutral typed boundary is live-verified with the configured OpenRouter model. |
| G. Plan validation | Done | Tool, policy, identity, graph, reference, output-field, type, and size checks exist. |
| H. Agent executor | Done | Dependency-aware deterministic execution, lifecycle, partial branches, Evidence accumulation, and Fact recomputation exist. |
| I. Budgets | Done | Attempts and retries consume one global adaptive-round budget. |
| J. Failure taxonomy | Partial | Connector/tool/provider failures are typed and sanitized; final V2 telemetry and phase distinctions are incomplete. |
| K. Retries / backoff | Done | Executor owns bounded transient retries; provider SDK retries are disabled. |
| L. Adaptive replanning | Done | Product workflow uses one planner across bounded rounds with updated state. |
| M. Action history / no progress | Done | Compact history reaches replanning and one no-progress round terminates deterministically. |
| N. ContextBuilder | Done | Deterministic, bounded, network-free context carries request, Facts, Evidence summaries, history, budget, rounds, and tools. |
| O. Provider / model routing | Partial | Planner and hypothesis routing work; code-diagnosis routing is not constructed or called. |
| P. Structured compatibility | Partial | Planner and hypothesis schemas pass live; code-diagnosis schema does not exist. |
| Q. Hypothesis generation | Done | Typed candidates reference Fact IDs; the configured provider passes live. |
| R. Hypothesis validation | Done | Generic Fact-family and entity validation prevents ungrounded candidates. |
| S. Grounded rendering | Done | Only validated hypotheses and Facts reach fixed backend wording. |
| T. Code-level diagnosis | Missing | No bounded input, typed candidate, deterministic location validator, or workflow stage. |
| U. Recommended remediation | Partial | A legacy action contract exists but no grounded developer remediation reaches the product result. |
| V. Persistence | Partial | Request, rounds, steps, Evidence, Facts, gaps, hypotheses, budget, termination, and result persist; code findings, recommendations, and generation metadata do not. |
| W. Live progress | Done at round boundary | Planned/completed rounds persist truthfully; per-step progress remains optional. |
| X. Question-first UI | Done | Question is primary; editable fixture-backed context preset is secondary. |
| Y. API | Partial | 202 creation and authoritative GET work; new validated diagnosis/remediation fields are absent. |
| Z. Polling / frontend state | Done | Polling is serialized, abortable, terminal-aware, and snapshot-authoritative. |
| AA. Observability | Partial | Generic HTTP/persistence/V1 spans exist and safe V2 error logs exist; required V2 stage spans/metrics are missing. |
| AB. Langfuse / LLMOps | Missing | No credentials, configuration, or integration exists. Runtime decisions must remain independent. |
| AC. Evals | Missing for V2 | Existing eval harness covers V1 explanations, not V2 components or trajectories. |
| AD. Real provider verification | Partial | Planner and hypothesis pass; code diagnosis and final provider-backed release trajectory remain. |
| AE. Real connector verification | Partial | Live adapters are tested with mocked HTTP; configured external GitHub/Jira reads remain to verify or gate. |
| AF. Startup / environment | Partial | Documented `.env` startup is explicit; current database credentials prevent live startup completion. |

## Proposed behavior

```text
question + typed context
-> deterministic ContextBuilder
-> task-routed typed planner
-> deterministic PlanValidator
-> budgeted read-only AgentExecutor
-> normalized Evidence -> deterministic Facts -> bounded replanning
-> typed hypothesis candidates -> deterministic hypothesis validator
-> bounded code context -> typed code-finding candidates
-> deterministic code-location/support validator
-> deterministic grounded remediation
-> persisted authoritative snapshot/result
-> polling API/UI projection
-> bounded OTel/Langfuse metadata and V2 eval evidence
```

## Scope

- In scope:
  - Repair the offline fake trajectory and release diagnostics.
  - Add the smallest code-diagnosis and grounded-remediation contracts and flow.
  - Persist and project validated diagnosis/remediation state.
  - Add V2-specific safe observability and optional Langfuse configuration.
  - Add deterministic component/trajectory evals plus bounded provider smoke.
  - Reconcile stale active plans and current architecture/product/testing docs.
- Expected systems and files:
  - `services/api/app/investigations/`, `app/workflows/investigation.py`
  - `services/api/app/runtime/`, `app/database/`, `app/api/v1/`
  - `services/api/app/observability/`, `app/evals/`, `app/main.py`, `app/config.py`
  - `services/api/tests/`, `apps/web/src/features/inspection/`
  - `docs/`, including architecture, product, testing, ADRs, learning log, and Mermaid flow

## Non-goals

- Write-capable tools, automatic remediation, natural-language intent extraction,
  RAG/vector search, queues/workers, WebSockets/SSE, distributed execution,
  crash resume, event sourcing, a semantic model router, or raw model prose.
- Treating grounded findings as proven production root cause.
- Provider or connector fallbacks that hide real failures.

## Acceptance criteria

- [ ] The fake fixture path exercises at least two planning rounds and produces
  persisted Evidence, Facts, a validated hypothesis, a validated code finding,
  and grounded remediation.
- [ ] Every LLM output remains a proposal until strict schema validation and a
  separate deterministic domain validator accept it.
- [ ] A fabricated file, hunk, symbol, Evidence ID, or Fact ID cannot reach the
  final API result.
- [ ] Planner, hypothesis, and code-diagnosis structured schemas pass a bounded
  live provider smoke using configured task models.
- [ ] One provider-backed investigation completes through the real adaptive
  workflow with fake connectors.
- [ ] Snapshot polling exposes only truthful backend state and stops terminally.
- [ ] V2 spans/metrics/logs contain allowlisted identifiers and counts, never
  prompts, raw code, Evidence payloads, credentials, or provider responses.
- [ ] Component and trajectory evals separate provider execution success,
  schema validity, deterministic grounding, and reference-answer quality.
- [ ] Full backend/frontend regression, compile, build, lint, diff, and secret
  checks pass; database and connector gates are either verified or explicit.

## Invariants

- Probabilistic stages may propose; deterministic code controls acceptance,
  execution, persistence, and exposure.
- Every Fact references existing Evidence; every final causal/code finding
  references accepted Facts and an observed code location.
- Tool calls remain read-only and every physical attempt consumes budget.
- The question crosses unchanged; external content never gains instruction authority.
- The frontend projects backend truth and never derives causal state.
- No secret, raw provider payload, raw prompt, or chain-of-thought is persisted,
  logged, traced, or rendered.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Provider authentication/rate/schema failure | Typed sanitized category; last truthful snapshot remains | Correct configuration/schema or retry only through the existing bounded policy |
| Invalid plan | No tool executes; deterministic termination is persisted | Fix planner prompt/schema; never bypass validation |
| Invalid diagnosis/remediation candidate | Candidate is rejected and excluded from final result | Inspect rejection code and strengthen proposal/eval data |
| Tool/connector failure | Typed failed step and missing information; unrelated branches may continue | Correct source/configuration; bounded transient retry only |
| Budget/no progress/round limit | Explicit termination with partial Evidence/Facts retained | Raise limits only through a measured policy change |
| PostgreSQL unavailable | Sanitized 503 or external release gate | Restore credentials/service; no fake persistence fallback |
| Telemetry/Langfuse export failure | Investigation behavior continues; bounded warning only | Restore exporter independently |

## Security

All external connector and model content is untrusted data. Tool definitions are
backend-owned, read-only, and allowlisted. Provider endpoints remain fixed for
credential isolation. Models never receive secrets, raw provider payloads, or
unbounded source data. Logs/traces use stable IDs, categories, counts, and safe
model/prompt identity only.

## Observability

Add nested investigation, planning-round, planner, plan-validation, tool,
Fact-derivation, hypothesis, diagnosis, validation, render, and termination
spans. Metrics use bounded labels only. Langfuse is optional and passive: it may
receive LLM generation metadata/correlation but cannot affect runtime decisions.

## Milestones

1. Runtime/startup/offline-path stability with a real fake fixture trajectory.
2. Typed code diagnosis and deterministic grounded remediation.
3. Persisted API/UI projection of validated diagnosis/remediation.
4. V2-specific OTel and optional Langfuse integration.
5. V2 component and trajectory evals.
6. Full release validation, live provider/connector/startup checks, and plan cleanup.

## Validation strategy

Run focused unit tests for each boundary before workflow/API/UI integration.
Then run full backend discovery, Python compilation, frontend tests/lint/build,
PostgreSQL integration when credentials work, bounded live provider diagnostics,
one provider-backed fake-connector investigation, connector smokes, startup
health, `git diff --check`, and a secret-pattern scan. Apply the required
`code-teacher-comments` pass only after each phase is functionally green, then
repeat affected checks.

## Progress

- [x] 2026-08-21: Read repository guidance, preserved untracked work, and
  established the Git baseline at merged master `ecdcc49`.
- [x] 2026-08-21: Audited A-AF across source, tests, docs, provider settings,
  persistence, frontend polling, observability, and evals.
- [x] 2026-08-21: Captured offline baseline and live OpenRouter planner and
  hypothesis evidence; identified the PostgreSQL authentication gate.
- [ ] Close and merge milestones 1-6.
- [x] 2026-08-21: Registered failure-location retrieval as a budgeted read-only
  tool, repaired the deterministic fake trajectory, and persisted safe planner,
  hypothesis, and action-history metadata.
- [x] 2026-08-21: Milestone 1 implementation and regression validation are
  complete: backend 376/376 with six external-database skips, frontend 38/38,
  compile/lint/build/diff checks green, and the updated planner schema passed a
  live strict-routing probe with the configured OpenRouter model.
- [x] 2026-08-21: Implemented the provider-neutral code-diagnosis component,
  deterministic Evidence-ID location resolver, and grounded remediation
  templates. Its live OpenRouter probe passed provider, schema, and grounding
  gates; workflow/API/UI integration remains Milestone 3.

## Decisions and discoveries

- Reuse `TypedLLMPlanner` for replanning and the existing persisted snapshot
  polling path; no second replanner or event architecture is needed.
- Keep code diagnosis as a new bounded proposal/validator stage after validated
  hypotheses. This extends the established trust boundary instead of expanding
  Fact derivation into probabilistic inference.
- Produce remediation deterministically from validated finding categories and
  support relationships. A second free-prose remediation LLM is unnecessary.
- Round-level checkpoints satisfy V2 truthful-progress requirements. Per-step
  callbacks remain optional unless implementation evidence shows a clean need.
- Database authentication failure is external configuration evidence, not a
  reason to weaken startup or persistence requirements.

## Risks and open questions

- Current Neon application/test credentials are rejected; database verification
  remains external until the repository owner rotates or restores them.
- Jira credentials exist, but a safe concrete issue key has not yet been
  established for a live read; discover one read-only or record the explicit gate.
- Langfuse credentials are absent. Implement only an optional, failure-isolated
  boundary supported by current dependencies or an approved minimal dependency.

## Completion

Pending implementation, final validation, Git history, release matrix, and
external-gate record. Move this plan to `completed` only when no implementation
gap remains.
