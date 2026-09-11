# Testing

## Current capability

Backend connector contracts, deterministic and mocked-HTTP connectors, policy,
runtime transitions, workflow execution, PostgreSQL safety gates,
observability, deterministic and real-adapter LLM explanations, and V1 HTTP behavior
have standard-library unit and integration tests:

```bash
cd services/api
uv run python -m unittest discover -s tests -v
```

The web workspace has manifest-backed build and lint commands:

```bash
bun run build:web
bun run lint:web
bun run test:web
```

The Bun tests validate frontend transport and server-rendered presentation
behavior. No root command currently validates the Python application.

`test_investigation_models.py` proves the V2.1 pure domain boundary: strict and
immutable requests, discriminated typed facts, categorical hypothesis
confidence and grounding, bounded missing-information/action codes, globally
unique entity IDs, resolvable internal references, and an insufficient-evidence
result that does not invent a fact or hypothesis. It uses no API, database,
connector, provider, or LLM dependency.

`test_evidence_models.py` proves the V2.2 evidence envelope and provenance
boundary: bounded identities and sources, discriminated typed content,
source/kind compatibility, timezone-aware source/retrieval times, clock-skew
tolerance, immutability, raw-payload rejection, duplicate identity rejection,
and resolvable fact/hypothesis evidence references. Missing source information
remains a typed `MissingInformation` value rather than fake evidence. The tests
make no connector, network, database, provider, or LLM call.

V2.3 GitHub code evidence is verified without live credentials by
`test_github_code_evidence_contracts.py`, `test_github_diff_parser.py`,
`test_github_code_http.py`, and `test_github_code_factory.py`. These tests cover
focused request/protocol/fake behavior, bounded unified-diff parsing, commit/PR/
file/hunk normalization, missing patches, rename and count invariants, ordered
pagination, explicit incomplete results, sanitized HTTP/network failures,
provider-data exclusion, bounded telemetry, and factory selection. The original
`test_github_http_connector.py` remains the separate V1 regression boundary.

`test_merge_readiness_api.py` proves the additive live-start route commits and
returns a pending ID before continuation, exposes running and terminal
snapshots through `GET /v1/runs/{run_id}`, preserves the synchronous route, and
keeps background connector failures as sanitized failed runs. The API test uses
a small threaded launcher only because the repository's synchronous
`TestClient` does not keep detached asyncio tasks alive between requests; the
application runtime uses its own asyncio task registry. `test_live_run_tasks.py`
proves application shutdown cancels unfinished in-process work.

`runPolling.test.ts` proves frontend snapshot refreshes are serialized, stop on
a terminal run, abort on stop, and report a temporary refresh failure without
turning it into a workflow failure. `RunDashboardPage.test.tsx` proves the
rendered developer view uses readable step labels, durations, source
provenance, sanitized errors, and only validated raw run JSON.

`test_github_http_connector.py` injects `httpx.MockTransport` into the real
`HttpGitHubConnector`. It exercises request handling, Pydantic response
validation, pagination, and normalization without opening a network connection.
This differs from `FakeGitHubConnector`: the fake selects complete internal
facts directly and remains an application mode, while mocked HTTP is only a
test transport and is never a third runtime mode.

`test_jira_http_connector.py` applies the same boundary to the real
`HttpJiraConnector`: minimal REST v3 responses, status-category normalization,
request construction, sanitized failures, and runtime integration run without
opening an Atlassian connection. `test_jira_connector_factory.py` proves fake
defaults and independent GitHub/Jira source selection.

`test_merge_readiness_explanations.py` injects deterministic, recording,
malformed, and failing LLM clients. It verifies minimized inputs, structured
generated claims, grounded reason/action coverage, deterministic rendering,
decision preservation, sanitized failures, persistence non-mutation, and
bounded telemetry without contacting a model provider. API integration tests
separately prove the existing validated response contract remains unchanged.
Provider-adapter tests also prove the explanation span carries prompt ID,
prompt version, provider, and a configured-model fingerprint while metrics
retain their closed low-cardinality label sets.

`test_llm_provider_factory.py` verifies the credential-free fake default,
OpenAI/Gemini/Groq configuration requirements, secret-free errors and
representations, fixed compatibility URLs, and `max_retries=0` SDK construction.
`test_openai_llm_client.py` injects a small
in-process SDK double. It proves Responses Structured Output request options,
token handling, deterministic-validator integration, refusal/invalid-response
handling, and the complete sanitized provider taxonomy. These tests do not
create OpenAI network traffic. `test_gemini_llm_client.py` injects the same SDK
boundary and proves Gemini's Chat Completions structured request, token mapping,
the low-complexity provider schema, strict PromptQL validator preservation,
refusal handling, Google's HTTP 400 invalid-key
normalization, and a sanitized structured failure log without opening a Google
connection.

`test_groq_llm_client.py` injects a Chat Completions SDK double. It proves the
Pydantic structured-output request, fixed factory endpoint, token mapping,
rate-limit and malformed-response normalization, deterministic-validator
preservation, bounded telemetry identity/model fingerprinting, and prose/secret
exclusion without opening a Groq connection. Eval tests prove `groq` appears in
run identity while preserving provider-attempt and candidate-quality
denominators.

PostgreSQL repository and migration tests are opt-in. They include source
provenance round trips and a pre-provenance nullable-row reconstruction. Without credentials they
report explicit skips and do not create an engine or connect to a database.

To run them, create a dedicated Neon test branch that contains no production
data, then set:

```text
TEST_DATABASE_URL=<dedicated test branch URL>
TEST_DATABASE_CONFIRMATION=promptql-test-database
DATABASE_URL=<application branch URL, used only for the inequality safety check>
```

Run the ordinary backend test command. The tests refuse to run when the test URL
is the application URL or the pooled/direct form of the same Neon branch. They
use `TEST_DATABASE_URL` as Alembic's target only inside the guarded test process
and clean up only run IDs created by the tests.

## Manual real-provider smoke test

Automated tests must never contact OpenAI, Gemini, or Groq. The opt-in live procedure
is in the root `README.md`. Run it only with a local API key, an explicitly selected
Structured Output-capable model, an authorized test request, and repository
owner approval. Inspect the final API explanation and bounded telemetry, but do
not print the prompt, model output, API key, headers, request IDs, or raw
exceptions.

## Evaluation quality distinctions

For AI features, distinguish provider success from candidate/model quality,
and distinguish schema validity from semantic grounding from ground-truth
correctness. Do not collapse these into one "accuracy" number. For
investigation hypotheses, grounded does not automatically mean correct root
cause. Offline correctness should rely on known gold/reference answers where
available; production correctness may require later human or operational
confirmation. Use LLM-as-a-judge only when appropriate and never treat it as
automatically authoritative.

## Versioned explanation evaluations

The local eval harness uses deterministic fake connector facts plus the
production policy, explanation input builder, provider adapter/parser, and
strict validator. It writes incremental JSONL observations and a completed JSON
report under ignored `services/api/local-artifacts/explanation-evals/`.

Run the complete three-sample development path without network access:

```powershell
uv run python -m app.evals.runner --fake-dry-run --dataset development --inter-request-delay-seconds 0
```

Preflight the configured provider without constructing a client or making an
external request:

```powershell
uv run --env-file .env python -m app.evals.runner --preflight --dataset development
uv run --env-file .env python -m app.evals.runner --preflight --dataset holdout
```

The default development run contains eleven cases times three samples: 33
planned calls. The default holdout contains six cases times three samples: 18
planned calls. Both default to one second between calls. A smaller learning
smoke run can pass `--samples-per-case 1`; this changes the experimental sample
count and cannot be compared with a three-sample baseline.

Real commands remain gated and require separate repository-owner approval:

```powershell
uv run --env-file .env python -m app.evals.runner --dataset development --acknowledge-paid-calls
uv run --env-file .env python -m app.evals.runner --dataset holdout --acknowledge-paid-calls
```

Do not add `--debug-holdout-details` to a release run. Normal holdout output and
JSONL omit per-case IDs and expected/observed claims. The debug flag reveals
those details locally and permanently spends the holdout for future unbiased
evaluation.

## OpenRouter provider-boundary diagnostics

The diagnostic module proves provider connectivity and typed generation without
starting FastAPI or PostgreSQL. Component stages isolate one boundary; the
`workflow` stage runs the production adaptive workflow with fake connectors and
in-memory persistence. Configuration output includes only provider/model names,
the fixed endpoint, and whether a key is present:

```powershell
uv run --env-file .env python -m app.diagnostics.openrouter --stage config
```

Network stages require explicit paid-call acknowledgement. Run them in order and
stop at the first failure:

```powershell
uv run --env-file .env python -m app.diagnostics.openrouter --stage plain --acknowledge-paid-call
uv run --env-file .env python -m app.diagnostics.openrouter --stage typed --acknowledge-paid-call
uv run --env-file .env python -m app.diagnostics.openrouter --stage planner --acknowledge-paid-call
uv run --env-file .env python -m app.diagnostics.openrouter --stage hypothesis --acknowledge-paid-call
uv run --env-file .env python -m app.diagnostics.openrouter --stage code-diagnosis --acknowledge-paid-call
uv run --env-file .env python -m app.diagnostics.openrouter --stage workflow --acknowledge-paid-call
```

Failures report only the exception class, HTTP status, provider error code/type,
sanitized provider message, requested model, endpoint/method, and any nested
upstream provider fields. The API key, authorization headers, request prompt,
evidence payload, and raw response are never printed. The optional
`planner-routing` stage probes OpenRouter's `require_parameters=true` routing
without changing production routing policy. The workflow stage makes at most
five calls: up to three planning rounds, then hypothesis and code diagnosis.
Its result contains only status, termination reason, model IDs, and counts.
`--stage all` retains the established component-only sequence; invoke the
workflow stage separately so its additional call bound is explicit.

For `openai/gpt-oss-120b`, use the configured upper bounds shown in `.env.example`
(`OPENROUTER_REQUEST_TIMEOUT_SECONDS=120` and
`OPENROUTER_MAX_OUTPUT_TOKENS=4096`). Reasoning tokens count against the output
allowance, so a small final JSON object can still end with
`length_finish_reason` under a 512- or 2048-token cap. This is a configuration
choice, not an SDK retry; production adapters still make one provider attempt.

Use `--save-baseline <path>` only for a completed formal run. A later run can
pass `--baseline <path>`; prompt, dataset, provider, configured model, model
settings, and sample count must be compatible. The report is written before a
quality/operational threshold returns exit code 1. Exit code 0 means execution
completed and release thresholds passed; 2 means configuration/safety failure;
3 means the requested baseline comparison is incompatible.

Artifacts cannot contain prompts, generated prose, connector payloads,
repository/Jira identity, credentials, raw responses, exception text, or cost
without explicit versioned pricing. Provider-total tokens are aggregated as an
independent provider measurement rather than assumed to equal input plus
output.

## Versioned V2 investigation evaluations

The V2 harness reuses production planners, validators, Fact derivation, code
diagnosis, recommendation templates, and the complete adaptive workflow with
deterministic fake connectors. It grades components and trajectories separately
without requiring one exact tool order.

Run the three-sample development and holdout paths without network access:

```powershell
uv run python -m app.evals.investigations.runner --fake-dry-run --dataset development --samples-per-case 3 --inter-request-delay-seconds 0
uv run python -m app.evals.investigations.runner --fake-dry-run --dataset holdout --samples-per-case 3 --inter-request-delay-seconds 0
```

Preflight the configured provider without constructing a client or making an
external request:

```powershell
uv run --env-file .env python -m app.evals.investigations.runner --preflight --dataset development --samples-per-case 1
```

The preflight reports requested task models and a conservative maximum of eight
provider calls per sample: three isolated component calls, up to three planner
rounds in the adaptive workflow, then workflow hypothesis and diagnosis calls.
A bounded real smoke requires explicit acknowledgement:

```powershell
uv run --env-file .env python -m app.evals.investigations.runner --dataset development --samples-per-case 1 --acknowledge-paid-calls
```

Exit code 0 means provider, schema, workflow-generation, component, and
trajectory gates all passed;
1 means execution completed but one or more release gates failed; 2 means a
configuration or safety gate failed. Reports under the ignored
`local-artifacts/investigation-evals/` directory contain aggregate IDs, rates,
latency, and token totals only. They omit questions, prompts, Evidence payloads,
code, generated output, credentials, raw exceptions, and unversioned cost.

Component quality is conditioned on successful component generation/schema
boundaries. Trajectory quality is conditioned on a successful workflow
generation boundary. An outage or invalid schema therefore fails its own gate
and leaves reasoning quality `n/a`; it is never counted again as a false quality
zero.

Development and holdout are versioned and use repeated probabilistic samples,
but the first catalog contains one checkout fixture family expressed with two
questions. Passing it proves the harness and supported scenario; it does not
establish broad production incident quality. Grounding and reference agreement
remain separate from true root-cause correctness.

## Fix-proposal eval matrix

A focused eval for the bounded fix-proposal boundary (ADR-038), separate from
the V2 investigation harness above: each case builds its hypothesis and code
finding deterministically (the real production validators, not an LLM), so
every provider call it makes is the fix-proposal call itself. Five fixed
fixture cases: KeyError/missing-mapping-key, None dereference, invalid input
boundary, configuration/deployment mismatch, and one deliberately ambiguous
case where correct abstention is the expected outcome.

Run the fifteen-sample offline path without network access:

```powershell
uv run python -m app.evals.fix_proposal.runner --fake-dry-run --inter-request-delay-seconds 0
```

Preflight the configured provider without constructing a client or making an
external request:

```powershell
uv run --env-file .env python -m app.evals.fix_proposal.runner --preflight
```

A bounded real smoke (one sample per case, five calls) requires explicit
acknowledgement:

```powershell
uv run --env-file .env python -m app.evals.fix_proposal.runner --samples-per-case 1 --acknowledge-paid-calls
```

Metrics are behavioral, not string-similarity: `correct_file`,
`correct_hunk_or_location`, `failure_mechanism_grounded` (deterministic
per-case keyword grounding), `minimal_edit` (line-level diff), an
`unsupported_identifier_rate` heuristic, `syntax_valid` (`ast.parse` on a
dedented hunk), `fix_available_when_expected`, and
`abstains_when_fix_not_grounded`. A real single-sample live run is expected
to show ordinary model variance (see ADR-038's "Live verification — fix
proposal" section) — `release_passed` on the fake-dry-run path is the
release gate; a single live sample is a smoke, not a threshold.

## Intended layers

| Layer | Intended location | Purpose | Status |
| --- | --- | --- | --- |
| Frontend unit/component | Near `apps/web/src` as `*.test.ts(x)` | Transport, response rendering, and loading state | Configured with Bun test; no browser DOM runner |
| Backend unit | `services/api/tests/unit` | Fake contracts, mocked GitHub/Jira HTTP normalization and errors, policy behavior, runtime transitions, and workflow execution | Configured with `unittest` discovery; no live provider calls |
| Backend API integration | `services/api/tests/integration` | V1 catalog, raw inspection, completed runs, typed failed runs, source provenance, retrieval, delegation, and validation | Configured with `unittest` discovery and FastAPI TestClient |
| Observability | `services/api/tests/unit/test_runtime_observability.py`, `test_investigation_observability.py`, and `services/api/tests/integration/test_observability_api.py` | In-memory V1/V2 spans and metrics, investigation stage hierarchy, model/token metadata, retries, bounded cardinality, durable terminal emission, redaction, independent general-OTLP/Langfuse setup, exporter isolation, and health exclusion | Runs without Grafana or Langfuse credentials; hosted export is an explicit external smoke |
| LLM explanation harness | `services/api/tests/unit/test_merge_readiness_explanations.py` | Minimized input, generated/validated trust separation, grounded code completeness, deterministic rendering, sanitized failures, persistence isolation, and safe telemetry | Internal fake/recording clients only; no real provider calls |
| OpenAI adapter | `services/api/tests/unit/test_llm_provider_factory.py`, `test_openai_llm_client.py` | Configuration, one-attempt SDK construction, Structured Output request shape, provider error normalization, token telemetry, validator preservation, and secret exclusion | Injected SDK boundary only; no external requests |
| Gemini compatibility adapter | `services/api/tests/unit/test_llm_provider_factory.py`, `test_gemini_llm_client.py` | Gemini-specific configuration, fixed Google endpoint, Chat Completions structured parsing, token mapping, validator preservation, and sanitized failures | Injected OpenAI SDK boundary only; no external requests |
| Groq/OpenRouter compatibility adapters | `services/api/tests/unit/test_llm_provider_factory.py`, `test_groq_llm_client.py` | Provider-specific configuration, fixed endpoints, strict-schema request shape, Groq-only reasoning control, sanitized structured-generation failures, validator preservation, and safe telemetry | Injected OpenAI SDK boundary only; no external requests |
| V2 adaptive investigation | `test_tool_registry.py`, `test_adaptive_investigation_runtime.py`, `test_investigation_workflow.py`, `test_grounded_hypotheses.py`, and `integration/test_investigation_api.py` | Registered read-only tools, plan validation/execution, global budget, round state, deterministic fake trajectory, grounded hypothesis and code-finding validation, recommendations, and persisted API projection | Offline fake checkout scenario exercises the real adaptive path through final diagnosis; external providers remain explicit smokes |
| V2 code diagnosis | `tests/unit/test_code_diagnosis.py`, `test_grounded_hypotheses.py`, workflow/API integration tests, and frontend response/dashboard tests | Bounded relevant context, schema failures, complete Fact/Evidence support, Evidence-ID location resolution, fabricated-location rejection, deterministic recommendation templates, persistence, and projection | Offline fake candidate plus an explicit paid OpenRouter provider/schema/grounding diagnostic |
| V2 investigation evals | `services/api/tests/unit/test_investigation_evals.py` | Versioned dev/holdout cases, component and trajectory graders, deterministic-baseline comparison, repeated samples, provider/schema separation, unsupported-claim rejection, call bounds, and aggregate-only artifacts | Automated and fake runs use deterministic clients/connectors; real runs require paid-call acknowledgement |
| Versioned explanation evals | `services/api/tests/unit/test_explanation_eval_*.py` | Development/holdout versioning, repeated samples, separate denominators, deterministic graders, pacing without retry, thresholds, safe artifacts, baselines, and paid-call gates | Automated tests use only fake/injected clients; real runs require approval |
| PostgreSQL integration | `services/api/tests/integration/test_postgres_runtime_persistence.py` | Alembic schema, durable reconstruction, ordering, provenance, legacy nullable rows, failures, and conflicts | Opt-in; skipped unless guarded test credentials are configured |
| Cross-layer/end-to-end | `tests/integration/test_investigation_api.py` plus frontend API/dashboard tests | API acceptance, persisted investigation snapshots, fixture-backed adaptive execution, and UI projection | Backend/frontend halves are automated; a browser runner is not configured |

Tests should assert observable behavior and invariants. Security boundaries,
external-data validation, failure behavior, and tenant separation require
explicit coverage when introduced.

## Unconfigured command placeholders

```text
End-to-end:     NOT CONFIGURED
```

Replace a placeholder only after adding and verifying the exact command.
## Validated explanation tests

`tests/unit/test_merge_readiness_explanations.py` proves exact deterministic
templates cover every policy code and that generated reason/action claims
cannot change the decision, invent or omit codes, duplicate claims, contradict
ready/unknown semantics, or bypass structure limits. It also proves generated
prose is discarded before deterministic rendering. The merge-readiness API
integration tests prove POST and GET retain the same schema and do not modify
the stored run; web tests continue proving response validation and rendering.
