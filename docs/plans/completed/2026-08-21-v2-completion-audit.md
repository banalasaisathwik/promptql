# Execution plan: V2 completion audit and release gate

- Status: Complete
- Owner: Repository owner
- Created: 2026-08-21
- Last updated: 2026-08-21
- Related ADRs: ADR-018, ADR-019, ADR-020, ADR-021, ADR-023, ADR-024, ADR-025,
  ADR-027, ADR-028, ADR-029
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

- [x] The fake fixture path exercises at least two planning rounds and produces
  persisted Evidence, Facts, a validated hypothesis, a validated code finding,
  and grounded remediation.
- [x] Every LLM output remains a proposal until strict schema validation and a
  separate deterministic domain validator accept it.
- [x] A fabricated file, hunk, symbol, Evidence ID, or Fact ID cannot reach the
  final API result.
- [x] Planner, hypothesis, and code-diagnosis structured schemas pass a bounded
  live provider smoke using configured task models.
- [x] One provider-backed investigation completes through the real adaptive
  workflow with fake connectors.
- [x] Snapshot polling exposes only truthful backend state and stops terminally.
- [x] V2 spans/metrics/logs contain allowlisted identifiers and counts, never
  prompts, raw code, Evidence payloads, credentials, or provider responses.
- [x] Component and trajectory evals separate provider execution success,
  schema validity, deterministic grounding, and reference-answer quality.
- [x] Full backend/frontend regression, compile, build, lint, diff, and secret
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
- [x] Close and merge milestones 1-6.
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
- [x] 2026-08-21: Milestone 3 integrated code diagnosis after validated
  hypotheses, persisted its safe metadata/findings/rejections/recommendations,
  rendered only grounded structures, and projected the strict contract through
  API and UI. Focused backend tests passed 64/64; frontend tests passed 40/40
  with lint and production build green before the final teaching-comment pass.
- [x] 2026-08-21: Milestone 4 added one correlated investigation trace with
  bounded spans and metrics for every planning/execution/grounding stage, safe
  provider-resolved model and token metadata, and independent general-OTLP and
  Langfuse OTLP exporters. Hosted Langfuse verification is externally gated by
  absent project credentials; offline instrumentation and redaction tests pass.
- [x] 2026-08-21: Milestone 5 added versioned V2 component and adaptive-
  trajectory evals with separate provider/schema/quality rates, deterministic
  baseline recall, unsupported-claim rejection, repeated sampling, bounded paid
  execution, and aggregate-safe artifacts. Three-sample fake development and
  holdout runs passed every gate; broader case diversity remains future quality
  work rather than an implementation blocker.
- [x] 2026-08-21: Milestone 6 live checks reached the configured OpenRouter,
  GitHub, Jira, Neon application database, and FastAPI startup boundaries. The
  provider-backed workflow completed safely with two rounds, five Evidence,
  two Facts, and one grounded hypothesis, then rejected an invalid second plan;
  the formal one-sample live eval failed provider reliability and left quality
  inconclusive. GitHub facts and V2 PR/file Evidence now pass live after making
  an omitted `merge_commit_sha` truly optional. Jira returned typed `not_found`
  for the PR-derived key, the application database is at Alembic head and
  `/health` is 200, while the separate test database credentials remain invalid.
- [x] 2026-08-21: Final offline release regression passed 410 backend tests
  with six environment-guarded PostgreSQL skips, full Python compilation, 40
  frontend tests, Oxlint, TypeScript compilation, and the Vite production build.
  Diff hygiene and secret-value checks passed; the intentionally failed
  `lint:web` invocation from `apps/web` was corrected to that package's
  manifest-backed `bun run lint` command.

## Decisions and discoveries

- Reuse `TypedLLMPlanner` for replanning and the existing persisted snapshot
  polling path; no second replanner or event architecture is needed.
- Keep code diagnosis as a new bounded proposal/validator stage after validated
  hypotheses. This extends the established trust boundary instead of expanding
  Fact derivation into probabilistic inference.
- Produce remediation deterministically from validated finding categories and
  support relationships. A second free-prose remediation LLM is unnecessary.
- Grade legal, grounded trajectory outcomes rather than exact tool ordering so
  semantically equivalent valid plans do not become false failures.
- Round-level checkpoints satisfy V2 truthful-progress requirements. Per-step
  callbacks remain optional unless implementation evidence shows a clean need.
- Application database authentication and startup now pass; separate guarded
  test-database authentication remains an external configuration gate and is
  not a reason to weaken persistence requirements.

## Risks and open questions

- The configured Neon application database works and is at migration head, but
  `TEST_DATABASE_URL` is still rejected; guarded PostgreSQL tests require its
  credential to be rotated or restored.
- Jira credentials reached the configured site, but the safe PR-derived key was
  not present there. A known harmless issue key from that exact site is required.
- The bounded OpenRouter eval and workflow smoke exposed provider timeouts and
  an invalid second-round plan. Deterministic controls behaved correctly, but a
  clean live eval release pass still requires provider/model reliability.
- Langfuse credentials are absent. Implement only an optional, failure-isolated
  boundary supported by current dependencies or an approved minimal dependency.
  The dependency-free OTLP boundary is now implemented; only hosted export
  verification remains gated.

## Completion

All in-repository implementation gaps identified by the A-AF audit are closed.
The remaining items are external verification/quality gates: a clean repeated
OpenRouter trajectory-eval pass, a harmless issue key belonging to the configured
Jira site, valid dedicated test-database credentials, hosted Langfuse credentials,
and deployed browser/telemetry verification. This plan moves to `completed` with
those gates preserved explicitly rather than weakening or simulating them.
