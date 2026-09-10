# Architecture decision records

ADRs preserve why durable choices were made. They complement the [current
architecture](../ARCHITECTURE.md): architecture says what exists now; ADRs
retain decision history and trade-offs.

## Statuses

- **Proposed:** under discussion; not authorization to implement.
- **Accepted:** approved and currently authoritative.
- **Superseded:** replaced by a newer ADR and retained as history.
- **Deprecated:** no longer recommended but not necessarily replaced.
- **Rejected:** considered and deliberately not selected.

Never rewrite an accepted historical ADR to make a later choice appear original.
Create a new ADR, mark the old one superseded, and link both.

## Register

| ADR | Status | Decision |
| --- | --- | --- |
| [ADR-001](ADR-001-versioned-connector-inspection-api.md) | Accepted | Versioned inspection endpoint, backend-owned demo fixture catalog, and relative `/v1` frontend routing |
| [ADR-002](ADR-002-merge-readiness-http-workflow.md) | Accepted | Additive merge-readiness endpoint with backend-owned policy decisions and supporting connector facts |
| [ADR-003](ADR-003-basic-runtime-execution.md) | Accepted | Synchronous runtime runs, recorded steps, replaceable storage, and typed HTTP 500 failed-run bodies |
| [ADR-004](ADR-004-durable-runtime-persistence.md) | Accepted | Neon PostgreSQL persistence through SQLAlchemy, Alembic migrations, short transactions, and run retrieval |
| [ADR-005](ADR-005-opentelemetry-observability.md) | Accepted | Provider-neutral OpenTelemetry traces and metrics, Grafana Cloud OTLP export, bounded telemetry, and post-commit terminal reporting |
| [ADR-006](ADR-006-read-only-github-rest-connector.md) | Accepted | Async read-only GitHub REST connector selected by configuration, normalized evidence, bounded pagination, and no fake fallback |
| [ADR-007](ADR-007-read-only-jira-cloud-connector.md) | Partially superseded by ADR-008 | Async read-only Jira Cloud REST connector, category-based status semantics, independent source selection, and honest unknown blocker normalization |
| [ADR-008](ADR-008-optional-jira-blocker-evidence.md) | Accepted | Treat unknown Jira blocker metadata as optional V1 evidence while explicit blockers remain blocking |
| [ADR-009](ADR-009-internal-llm-explanation-harness.md) | Partially superseded by ADR-010 | Internal provider-neutral explanation harness with minimized policy input and deterministic fake generation |
| [ADR-010](ADR-010-strict-explanation-validation-and-ui.md) | Partially superseded by ADR-011 | Exact backend-owned explanation templates, additive read-time API enrichment, and frontend rendering |
| [ADR-011](ADR-011-grounded-explanation-code-validation.md) | Accepted | Ground untrusted generated reason/action codes in policy facts before deterministic rendering |
| [ADR-012](ADR-012-openai-structured-explanation-adapter.md) | Accepted | Optional async OpenAI Responses Structured Output adapter behind the existing deterministic validation boundary |
| [ADR-013](ADR-013-gemini-openai-compatible-explanation-adapter.md) | Partially superseded by ADR-014 | Explicit Gemini provider using the OpenAI SDK with a fixed Google compatibility endpoint and unchanged deterministic validation |
| [ADR-014](ADR-014-gemini-compact-claim-indexes.md) | Accepted | Use compact request-local indexes for Gemini claims before strict typed and semantic validation |
| [ADR-015](ADR-015-versioned-explanation-eval-harness.md) | Accepted | Version local explanation datasets, repeated samples, graders, thresholds, and compatible baselines |
| [ADR-016](ADR-016-durable-run-source-provenance.md) | Accepted | Persist bounded GitHub, Jira, and explanation source provenance and render typed failed runs |
| [ADR-017](ADR-017-groq-openai-compatible-explanation-adapter.md) | Accepted | Add explicit Groq identity through the fixed OpenAI-compatible endpoint with unchanged deterministic validation |
| [ADR-018](ADR-018-live-run-dashboard-snapshot-polling.md) | Accepted | Additive 202 live-start endpoint with in-process execution and persisted-snapshot polling |
| [ADR-019](ADR-019-investigation-domain-contracts.md) | Accepted | Minimal typed investigation facts, explicit hypotheses and unknowns, and deterministic result invariants |
| [ADR-020](ADR-020-first-class-investigation-evidence.md) | Accepted | Provider-neutral immutable evidence envelope with typed content, provenance, and result-level reference validation |
| [ADR-021](ADR-021-focused-github-code-evidence-source.md) | Accepted | Focused read-only GitHub code-evidence protocol with bounded normalization, pagination, and diff parsing |
| [ADR-023](ADR-023-bounded-tool-retry-policy.md) | Accepted | Typed transient failure classification and executor-owned bounded retries charged to the shared tool-call budget |
| [ADR-024](ADR-024-grounded-hypothesis-proposals.md) | Accepted | Bounded LLM hypothesis proposals with deterministic Fact-relationship validation |
| [ADR-025](ADR-025-investigation-console-snapshot-integration.md) | Accepted | Investigation console uses the existing persisted run snapshot and polling mechanism |
| [ADR-026](ADR-026-budgeted-failure-location-evidence.md) | Accepted | Collect failure-location Evidence through the validated, budgeted read-only tool runtime |
| [ADR-027](ADR-027-evidence-identified-code-diagnosis.md) | Accepted | Let models select an observed code-location Evidence ID while deterministic code resolves coordinates and remediation |
| [ADR-028](ADR-028-passive-langfuse-otlp-generation-tracing.md) | Accepted | Export bounded investigation generation spans to optional Langfuse through a second failure-isolated OTLP trace exporter |
| [ADR-029](ADR-029-versioned-investigation-component-trajectory-evals.md) | Accepted | Evaluate V2 components and adaptive trajectories with versioned reference cases, deterministic graders, repeated sampling, and separate provider/schema/quality metrics |
| [ADR-030](ADR-030-openrouter-openai-compatible-explanation-adapter.md) | Accepted | Add explicit OpenRouter identity through the fixed OpenAI-compatible endpoint, reusing the Groq adapter by subclassing it |
| [ADR-031](ADR-031-repository-scoped-fact-recurrence-memory.md) | Accepted | Deterministically count Fact-type recurrence per repository across investigation runs as a new, non-Fact domain concept; defer LLM-proposed richer memory |
| [ADR-032](ADR-032-read-only-sentry-rest-connector.md) | Accepted | Self-contained read-only Sentry REST `IncidentSource`, always-`None` environment/category, `version:environment` deployment references, and one-time live-verified free-tier fragility mitigation |
| [ADR-033](ADR-033-reopening-completed-investigations-for-follow-up.md) | Accepted | Scope reopening a completed investigation to a repository-layer `isinstance(run, InvestigationRun)` exception, leaving `ALLOWED_RUN_TRANSITIONS`/`RunStatus` and merge-readiness untouched; accumulate budget, continue round numbering, dedupe fact-recurrence per case, cap follow-ups at 3, and store an ordered append-only result sequence |
| [ADR-034](ADR-034-multi-user-auth-and-per-user-credential-storage.md) | Accepted | All 4 phases implemented: `users` table with Argon2id password hashing (`argon2-cffi`) and signed/httponly/secure/samesite=lax session cookies (`itsdangerous`); encrypted per-user GitHub/Jira/Sentry credential storage (Fernet); `get_github_connector`/`get_jira_connector`/`get_incident_source` rewired to per-request, per-user resolution while the anonymous path stays unmodified; and `user_id`-scoped ownership isolation for investigation runs |
| [ADR-035](ADR-035-demo-account-landing-page-bypass.md) | Accepted | Public landing page with a "Try the Demo" button that logs into a pre-provisioned `is_demo` account; an `is_demo` bypass makes `get_github_connector`/`get_jira_connector`/`get_incident_source`/`get_github_code_evidence_source` skip stored-credential lookup entirely for that account and return the existing anonymous fake connector, and `/v1/credentials` reports it as connected with a `source: "demo"` marker rather than touching real storage |
| [ADR-036](ADR-036-commit-scoped-code-change-evidence.md) | Accepted | Add a commit-scoped `get_commit_changed_file_evidence` connector method, new `CommitChangedFileEvidenceContent`/`CommitDiffHunkEvidenceContent` correlated by `commit_sha`, a parallel fact-derivation branch, and a new `GET_COMMIT_DIFF` tool wired unconditionally into the deterministic baseline, so investigations can derive code-change facts from commits with no associated pull request |
| [ADR-037](ADR-037-deterministic-correlation-path-for-repo-only-input.md) | Proposed | A second, repo-only entry point bypassing the LLM planner entirely for deterministic PR/Sentry-issue/Jira-ticket correlation. Phases 1-2 implemented and live-verified: `HttpSentrySource.list_open_issues` (Sentry's `Link`-header cursor pagination, not GitHub's silent cap) and `.get_linked_jira_key` (the link lives only at `GET /organizations/{org}/issues/{id}/integrations/`'s `externalIssues[0].key`, never on the ordinary issue-detail response). Phases 3-4 (the orchestrator and entry point) still planned |
