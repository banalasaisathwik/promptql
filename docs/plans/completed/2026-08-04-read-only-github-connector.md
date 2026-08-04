# Execution plan: Read-only GitHub connector

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-04
- Last updated: 2026-08-04
- Related ADRs: ADR-006

## Objective and behavior

Preserve deterministic fake mode while adding an explicitly configured,
read-only GitHub REST implementation behind the same typed asynchronous
protocol. The merge-readiness workflow receives normalized facts and never
branches on connector source.

## Scope and invariants

- Validate configuration and select the connector at FastAPI assembly.
- Normalize PR, review, repository-rule, check-run, and commit-status evidence.
- Bound pagination and sanitize all provider failures.
- Preserve blocker-over-unknown policy precedence and all fake scenarios.
- Never call GitHub from automated tests; never fall back to fixtures in live
  mode; never emit or persist tokens or raw provider responses.

OAuth, GitHub Apps, retries, caching, webhooks, Jira HTTP, source schema
migrations, and live automated tests are non-goals.

## Failure behavior

Invalid mode, token, base URL, or timeout fails configuration. Authentication,
permission, rate-limit, not-found, timeout, upstream, and response-validation
failures enter a closed connector taxonomy. During workflow execution they use
the existing sanitized connector-failure runtime semantics. Unavailable rules
or review evidence becomes missing information rather than invented facts.

## Validation and completion

- `uv run python -m unittest tests.unit.test_github_http_connector tests.unit.test_github_connector_factory -v`: 21 passed.
- `uv run python -m unittest discover -s tests`: 91 passed, four PostgreSQL
  integration tests skipped without `TEST_DATABASE_URL`.
- `bun run test:web`: seven passed; `bun run build:web` and
  `bun run lint:web` both passed.

The architecture, testing guide, environment example, ADR, learning log, and
local ignored Mermaid flow were updated to match the implementation.
