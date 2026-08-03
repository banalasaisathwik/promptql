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
