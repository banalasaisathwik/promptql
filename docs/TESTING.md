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

## Intended layers

| Layer | Intended location | Purpose | Status |
| --- | --- | --- | --- |
| Frontend unit/component | Near `apps/web/src` as `*.test.ts(x)` | Transport, response rendering, and loading state | Configured with Bun test; no browser DOM runner |
| Backend unit | `services/api/tests/unit` | Fake contracts, mocked GitHub/Jira HTTP normalization and errors, policy behavior, runtime transitions, and workflow execution | Configured with `unittest` discovery; no live provider calls |
| Backend API integration | `services/api/tests/integration` | V1 catalog, raw inspection, completed runs, typed failed runs, source provenance, retrieval, delegation, and validation | Configured with `unittest` discovery and FastAPI TestClient |
| Observability | `services/api/tests/unit/test_runtime_observability.py` and `services/api/tests/integration/test_observability_api.py` | In-memory spans/metrics, hierarchy, durable terminal emission, redaction, exporter isolation, health exclusion | Runs without Grafana credentials |
| LLM explanation harness | `services/api/tests/unit/test_merge_readiness_explanations.py` | Minimized input, generated/validated trust separation, grounded code completeness, deterministic rendering, sanitized failures, persistence isolation, and safe telemetry | Internal fake/recording clients only; no real provider calls |
| OpenAI adapter | `services/api/tests/unit/test_llm_provider_factory.py`, `test_openai_llm_client.py` | Configuration, one-attempt SDK construction, Structured Output request shape, provider error normalization, token telemetry, validator preservation, and secret exclusion | Injected SDK boundary only; no external requests |
| Gemini compatibility adapter | `services/api/tests/unit/test_llm_provider_factory.py`, `test_gemini_llm_client.py` | Gemini-specific configuration, fixed Google endpoint, Chat Completions structured parsing, token mapping, validator preservation, and sanitized failures | Injected OpenAI SDK boundary only; no external requests |
| Groq compatibility adapter | `services/api/tests/unit/test_llm_provider_factory.py`, `test_groq_llm_client.py` | Groq-specific configuration, fixed endpoint, strict-schema request, token mapping, validator preservation, sanitized failures, and safe telemetry | Injected OpenAI SDK boundary only; no external requests |
| Versioned explanation evals | `services/api/tests/unit/test_explanation_eval_*.py` | Development/holdout versioning, repeated samples, separate denominators, deterministic graders, pacing without retry, thresholds, safe artifacts, baselines, and paid-call gates | Automated tests use only fake/injected clients; real runs require approval |
| PostgreSQL integration | `services/api/tests/integration/test_postgres_runtime_persistence.py` | Alembic schema, durable reconstruction, ordering, provenance, legacy nullable rows, failures, and conflicts | Opt-in; skipped unless guarded test credentials are configured |
| Cross-layer/end-to-end | Future repository-level area | Browser-to-API journeys | Planned; tooling not selected |

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
