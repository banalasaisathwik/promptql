# Testing

## Current capability

Backend connector contracts, deterministic and mocked-HTTP connectors, policy,
runtime transitions, workflow execution, PostgreSQL safety gates,
observability, and V1 HTTP behavior have standard-library unit and integration
tests:

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

PostgreSQL repository and migration tests are opt-in. Without credentials they
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

## Intended layers

| Layer | Intended location | Purpose | Status |
| --- | --- | --- | --- |
| Frontend unit/component | Near `apps/web/src` as `*.test.ts(x)` | Transport, response rendering, and loading state | Configured with Bun test; no browser DOM runner |
| Backend unit | `services/api/tests/unit` | Fake contracts, mocked GitHub/Jira HTTP normalization and errors, policy behavior, runtime transitions, and workflow execution | Configured with `unittest` discovery; no live provider calls |
| Backend API integration | `services/api/tests/integration` | V1 catalog, raw inspection, completed runs, typed failed runs, delegation, and validation | Configured with `unittest` discovery and FastAPI TestClient |
| Observability | `services/api/tests/unit/test_runtime_observability.py` and `services/api/tests/integration/test_observability_api.py` | In-memory spans/metrics, hierarchy, durable terminal emission, redaction, exporter isolation, health exclusion | Runs without Grafana credentials |
| PostgreSQL integration | `services/api/tests/integration/test_postgres_runtime_persistence.py` | Alembic schema, durable reconstruction, ordering, failures, and conflicts | Opt-in; skipped unless guarded test credentials are configured |
| Cross-layer/end-to-end | Future repository-level area | Browser-to-API journeys | Planned; tooling not selected |
| Agent evaluations | `evals` when introduced | Quality and regressions | Planned; area absent |

Tests should assert observable behavior and invariants. Security boundaries,
external-data validation, failure behavior, and tenant separation require
explicit coverage when introduced.

## Unconfigured command placeholders

```text
End-to-end:     NOT CONFIGURED
Agent evals:    NOT CONFIGURED
```

Replace a placeholder only after adding and verifying the exact command.
