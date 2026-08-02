# Testing

## Current capability

Backend connector contracts, deterministic merge-readiness policy, and V1 HTTP
behavior have standard-library unit and integration tests:

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

## Intended layers

| Layer | Intended location | Purpose | Status |
| --- | --- | --- | --- |
| Frontend unit/component | Near `apps/web/src` as `*.test.ts(x)` | Transport, response rendering, and loading state | Configured with Bun test; no browser DOM runner |
| Backend unit | `services/api/tests/unit` | Connector contracts and pure policy behavior | Configured with `unittest` discovery |
| Backend API integration | `services/api/tests/integration` | V1 catalog, raw inspection, merge readiness, HTTP failures, and determinism | Configured with `unittest` discovery and FastAPI TestClient |
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
