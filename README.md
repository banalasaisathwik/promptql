# PromptQL

PromptQL is an early-stage enterprise investigation and analytics agent inspired
by PromptQL-like systems. This repository currently provides the frontend,
backend, documentation, testing, and agent-development foundations; it does not
yet contain the complete agent runtime.

## Repository layout

| Path | Purpose |
| --- | --- |
| `apps/web` | Vite, React, and TypeScript browser application |
| `services/api` | FastAPI Python API managed with `uv` |
| `packages` | Reserved for reusable TypeScript packages |
| `docs` | Product, architecture, testing, decision, task, plan, and learning documentation |
| `infra` | Reserved for infrastructure configuration |
| `scripts` | Reserved for repository automation |

## Prerequisites

- Bun
- Python 3.13 or newer
- uv
- Git
- A managed Neon PostgreSQL project for durable runtime execution

## Setup and run

From the repository root:

```bash
bun install
bun run dev:web
```

From `services/api`:

```bash
uv sync
```

Use `.env.example` as a reference and set these values in the shell environment
that runs Alembic and FastAPI:

```text
DATABASE_URL=<pooled Neon PostgreSQL URL>
DATABASE_MIGRATION_URL=<direct Neon PostgreSQL URL>
```

GitHub uses deterministic fixtures by default:

```text
PROMPTQL_GITHUB_CONNECTOR=fake
```

To run the read-only live connector, set `PROMPTQL_GITHUB_CONNECTOR=github`
and provide a local `GITHUB_TOKEN`. Do not commit the token. Live mode never
falls back to fixture data after a GitHub failure.

Telemetry is safe and disabled by default. To inspect spans and metrics locally
without an external service, opt into console exporters:

```text
PROMPTQL_TELEMETRY_ENABLED=true
PROMPTQL_TELEMETRY_CONSOLE_ENABLED=true
OTEL_SERVICE_NAME=promptql-api
```

For Grafana Cloud, keep the console exporter disabled and set the provider's
OTLP base URL and encoded authorization header. Use real values only in your
local environment or secret manager:

```text
PROMPTQL_TELEMETRY_ENABLED=true
PROMPTQL_TELEMETRY_CONSOLE_ENABLED=false
OTEL_SERVICE_NAME=promptql-api
OTEL_EXPORTER_OTLP_ENDPOINT=<https OTLP base URL ending in /otlp>
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<base64-instance-id-and-token>
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

The application appends `/v1/traces` and `/v1/metrics` to that base endpoint.
Do not commit `.env`, API tokens, or rendered authorization headers.

Apply migrations explicitly, then start the API:

```bash
uv run alembic upgrade head
uv run fastapi dev app/main.py
```

The repository does not yet provide one command that starts both applications.
The API never creates tables or runs migrations automatically at startup.

Run credential-free backend tests with:

```bash
uv run python -m unittest discover -s tests -v
```

PostgreSQL integration tests require a dedicated test branch and the explicit
environment variables documented in [TESTING.md](docs/TESTING.md).

## Manual live GitHub smoke test

This procedure is manual because ordinary tests never contact GitHub.

1. In the shell that will start FastAPI, set the database values above and:

   ```powershell
   $env:PROMPTQL_GITHUB_CONNECTOR = "github"
   $env:GITHUB_TOKEN = "<local fine-grained token>"
   $env:GITHUB_API_BASE_URL = "https://api.github.com"
   $env:GITHUB_REQUEST_TIMEOUT_SECONDS = "10"
   ```

2. From `services/api`, apply migrations and start the API:

   ```powershell
   uv run alembic upgrade head
   uv run fastapi dev app/main.py
   ```

3. In a second PowerShell window, inspect one repository and pull request that
   the token may read:

   ```powershell
   $requestBody = @{
       repository_owner = "<owner>"
       repository_name = "<repository>"
       pr_number = 123
   } | ConvertTo-Json

   $run = Invoke-RestMethod `
       -Method Post `
       -Uri "http://127.0.0.1:8000/v1/pull-request-merge-readiness" `
       -ContentType "application/json" `
       -Body $requestBody

   $run
   Invoke-RestMethod "http://127.0.0.1:8000/v1/runs/$($run.run_id)"
   ```

   Verify that authentication and repository access succeed, GitHub fields are
   normalized and persisted, and connector spans identify `source=live` when
   telemetry is enabled. Because Jira HTTP is not implemented, a live run is
   normally `unknown` unless verified GitHub evidence makes it `blocked`.

4. Stop FastAPI and switch back to deterministic fixtures:

   ```powershell
   $env:PROMPTQL_GITHUB_CONNECTOR = "fake"
   Remove-Item Env:GITHUB_TOKEN -ErrorAction SilentlyContinue
   ```

Start with the [documentation index](docs/index.md) before making changes.
