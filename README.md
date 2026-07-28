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

## Setup and run

From the repository root:

```bash
bun install
bun run dev:web
```

From `services/api`:

```bash
uv sync
uv run fastapi dev app/main.py
```

The repository does not yet provide one command that starts both applications.
Environment-variable setup, production deployment, and test commands are also
not configured yet.

Start with the [documentation index](docs/index.md) before making changes.
