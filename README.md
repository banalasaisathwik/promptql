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

Start with the [documentation index](docs/index.md) before making changes.
