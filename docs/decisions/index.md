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
