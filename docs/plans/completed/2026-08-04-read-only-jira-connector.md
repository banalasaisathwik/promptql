# Execution plan: Read-only Jira Cloud connector

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-04
- Last updated: 2026-08-04
- Related ADRs: ADR-006; ADR-007

## Objective and completed behavior

The independently configured asynchronous Jira boundary now selects either
deterministic fixture facts or one read-only Jira Cloud REST v3 issue lookup.
The workflow passes only the validated GitHub-extracted key, receives normalized
facts, and remains unaware of authentication, raw JSON, or source mode.

## Preserved invariants and boundaries

- Fake/fake remains the credential-free default and deterministic scenarios pass.
- GitHub and Jira independently support fake/live source combinations.
- Custom status names never determine completion; category keys do.
- Missing standard blocker evidence is explicit unknown, never assumed clear.
- Live failures never fall back and persist only the existing sanitized runtime
  connector error.
- One issue request selects only status, assignee, and resolution; comments,
  changelog, pagination, writes, retries, and OAuth remain absent.
- Credentials, authorization, external payloads, identities, and URLs are
  excluded from errors and telemetry.
- Optional Jira snapshot fields fit existing JSONB; no migration was added.

## Verification

- `uv run python -m compileall -q app tests`: passed.
- Focused Jira connector/factory suite: 18 passed.
- GitHub connector/factory regression suite: 21 passed.
- `uv run python -m unittest discover -s tests`: 111 passed; four PostgreSQL
  integration tests skipped without `TEST_DATABASE_URL`.
- `bun run test:web`: seven passed.
- `bun run build:web` and `bun run lint:web`: passed.
- `git diff --check`: passed.
- MockTransport/source inspection found no live provider calls; migration diff
  and production-source secret scans were empty.

ADR-007, architecture, product, testing, environment example, manual smoke
procedure, learning log, and the ignored detailed Mermaid flow now describe the
verified implementation and its unknown-blocker limitation.
