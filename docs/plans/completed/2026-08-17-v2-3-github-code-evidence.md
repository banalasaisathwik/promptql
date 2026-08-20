# Execution plan: V2.3 GitHub code and diff evidence

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-17
- Last updated: 2026-08-17
- Related ADRs: ADR-020, ADR-021
- Related tasks: None

## Objective

Retrieve investigation-relevant commit, pull-request, changed-file, and patch
information through a focused read-only GitHub boundary and return validated,
provider-neutral V2.2 evidence.

## Current behavior and evidence

V2.2 commit `340ff1f` defines immutable evidence but no provider constructs it.
V1 `GitHubConnector.get_pull_request()` returns merge-readiness facts and must
remain unchanged. A 54-test baseline covering V1 GitHub and V2.1/V2.2 models
passed before V2.3 edits.

## Proposed behavior

```text
GitHub REST JSON
-> private strict response models
-> focused HTTP adapter
-> enum/count/timestamp normalization
-> bounded unified-diff parsing
-> immutable V2 Evidence
```

Commit, PR, file, and hunk evidence are independently identifiable. Missing
patch content is explicit. Pagination or parser-bound exhaustion is a typed
incomplete result rather than a partial success.

## Scope

- In scope: evidence schema extensions, focused protocol, deterministic fake,
  live HTTP adapter, bounded parser, factory wiring, telemetry allowlist,
  focused tests, ADR/docs/learning/Mermaid updates.
- Expected systems and files: `app/investigations`, `app/connectors`,
  `app/observability`, corresponding unit tests, and V2 documentation.

## Non-goals

- No fact derivation, commit-to-PR fact, incident/deployment/stack matching,
  planner tools, planner, LLM, runtime, persistence, API, frontend, retries,
  queues, AST parsing, repository indexing, or live GitHub call.

## Acceptance criteria

- [x] Focused fake/live provider boundary returns only V2 evidence.
- [x] Commit and PR metadata are normalized without identity/email leakage.
- [x] Added, modified, removed, and renamed files normalize deterministically.
- [x] Patch absence is explicit; present patches become bounded typed hunks.
- [x] Pagination preserves order and fails explicitly when incomplete.
- [x] Sanitized provider failures remain distinct.
- [x] V1 GitHub behavior and V2.1/V2.2 validation remain green.
- [x] Documentation marks only V2.3 provider evidence implemented.

## Invariants

- Raw GitHub JSON and response objects never leave the adapter.
- Every output passes the V2.2 evidence contracts.
- Evidence IDs and source references are stable for the normalized source entity.
- Hunk counts agree with context/addition/deletion line consumption.
- No partial page or bounded patch is reported as complete.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| 401/403/404/429/5xx | Existing sanitized typed GitHub error | Correct access/configuration or retry later outside V2.3 |
| Timeout/network | Sanitized timeout/unavailable error | Caller decides later retry policy |
| Invalid JSON/schema/status | `GitHubInvalidResponseError` | Inspect adapter fixture/provider contract safely |
| Page or patch bound reached | `GitHubIncompleteResultError` | Narrow request or deliberately revise a measured bound |
| Patch omitted | File evidence has `patch_available=False`, no hunks | Treat as unavailable evidence, not an empty diff |

## Security

Reuse the application-scoped read-only token and HTTP client. Do not serialize
headers, tokens, raw bodies, profiles/emails, provider exceptions, temporary
URLs, or unrestricted payloads. Bound all retained patch lines.

## Observability

Reuse connector spans for bounded commit/PR/file operations, result category,
HTTP status class, and page count. Never add repository, SHA, PR, path, or patch
content as span attributes or metric labels.

## Milestones

1. Extend domain contracts and validate focused request/protocol/fake behavior.
2. Implement response validation, parsing, HTTP normalization, and failures.
3. Document, teaching-comment, fully validate, audit, and archive the plan.

## Validation strategy

Run domain/parser tests first, then HTTP/factory/V1 regression tests, compileall,
the complete backend suite, `git diff --check`, forbidden-boundary searches, and
the mandatory final teaching-comment pass with affected tests rerun.

## Progress

- [x] 2026-08-17: Verified V2.2 commit, branch dependency, dirty-file ownership,
  required repository sources, baseline tests, and official GitHub REST behavior.
- [x] 2026-08-17: Resolved focused protocol in ADR-021.
- [x] 2026-08-17: Implemented evidence extensions, protocol, fake, adapter, parser.
- [x] 2026-08-17: Added focused and regression tests; 95 combined tests passed.
- [x] 2026-08-17: Updated documentation, applied the teaching-comment pass,
  reran 95 focused/regression and 278 complete backend tests, and audited scope.

## Decisions and discoveries

GitHub documents a 3,000-file maximum for PR file responses. V2.3 uses explicit
local page bounds and does not claim completeness after bound exhaustion.
Commit-to-PR association exists in GitHub REST but is not required by the three
current operations and remains non-authoritative/deferred.

## Risks and open questions

- Initial patch line/hunk bounds require revision only if measured legitimate
  responses exceed them.
- The branch is temporarily stacked on V2.2 because V2.1/V2.2 are not merged to master.

## Completion

V2.3 is implemented and validated as a focused provider capability. Compilation,
95 combined regression tests, and 278 complete backend tests passed with six
environment-guarded PostgreSQL skips. Patch integrity, V1 non-regression, raw-
provider/security boundaries, ignored Mermaid documentation, and deferred-scope
searches passed. No live GitHub call, commit, push, or V2.4 implementation occurred.
