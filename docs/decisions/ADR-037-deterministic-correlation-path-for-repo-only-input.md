# ADR-037: Deterministic correlation path for repo-only input

- Status: Proposed (Phases 1-2 decided and implemented; Phases 3-4 planned, not yet built)
- Date: 2026-09-08
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

The current investigation flow requires `incident_reference`/
`pull_request_number`/`deployment_reference` as input and routes everything
through `TypedLLMPlanner` → `AdaptiveInvestigationRuntime` (up to 3 LLM
planning rounds) → hypothesis generation → code diagnosis, even when the
actual answer is a deterministic fact-derivation correlation (PR ↔ Sentry
issue ↔ Jira ticket). A diagnostic audit (2026-09-08) confirmed
`fact_derivation/deployment.py` and `fact_derivation/code_change.py` are
pure functions requiring no LLM. The only real gaps were connector
capabilities, not orchestration — specifically, no capability existed to
*discover* which Sentry issues are open for a repository's project, or to
resolve a Sentry issue's linked Jira ticket, without already knowing a
specific `incident_reference` up front.

`incident_reference`-first input works for "why did *this* incident break"
questions but cannot answer "what's currently open across this repo" — a
different, repo-scoped question this ADR adds a separate, deterministic
path for.

## Decision drivers

- Correctness: a deterministic correlation (issue exists, is linked to a
  commit with no PR, is linked to a Jira ticket) should never require an
  LLM call or be exposed to planner hallucination risk.
- Cost/latency: the existing planner-driven flow pays for at least one LLM
  call even when nothing about the answer is probabilistic.
- Reversibility/testability: a repo-only scan must not require special-
  casing inside `AdaptiveInvestigationRuntime`'s planner/executor/budget
  machinery, which is designed around plan validation and step retries a
  fixed correlation scan doesn't need.
- Learning: separates "probabilistic reasoning may propose, deterministic
  code controls what is accepted" (CLAUDE.md's Core V2 principle) from
  "some answers were never probabilistic to begin with."

## Options considered

### Option A: Add a "fast mode" flag to the existing planner-driven flow

Rejected — still pays for at least one LLM planning call per run, so it
doesn't remove the actual bottleneck (planner latency/cost), and it
conflates two different mental models (adaptive investigation vs.
deterministic scan) inside one code path.

### Option B: Full replacement of the planner-driven flow with the deterministic scan

Rejected — the existing flow is still needed for open-ended "why did X
break" questions with no repository-wide scan intent and no fixed call
sequence that could answer them; a deterministic scan cannot substitute for
adaptive, hypothesis-driven investigation.

### Option C: A second, separate entry point with a fixed call sequence

`InvestigationWorkflowService.run_correlation_scan` (name TBD) takes only
`{repo}` and executes a hardcoded sequence of direct connector/fact-
derivation calls — no planner, no plan validator, no supervisor loop, no
hypothesis or code-diagnosis stages. The existing planner-driven flow is
untouched for callers who supply a specific incident/deployment reference
and want a causal narrative. Chosen: it keeps the deterministic path
genuinely deterministic (no shared state or control flow with the
LLM-driven path) while reusing the already-pure `fact_derivation` functions
directly.

## Decision

Add a second entry point (Option C) that takes only `{repo}` and produces a
flat, per-issue correlation list — no hypothesis, no rendering through
`render_grounded_result`. Two blocking connector capabilities were required
before any orchestration code could be written, and both are now decided
and implemented (Phases 1-2 below); Phases 3-4 (the orchestrator itself and
its entry point) are still planned, not yet built.

### Phase 1 — Sentry: list open issues for a project/release (IMPLEMENTED)

`HttpSentrySource.list_open_issues(SentryOpenIssuesRequest)` calls
`GET /projects/{org}/{project_slug}/issues/?query=is:unresolved[+release:{version}]`
— verified live against a real Sentry org (`student-whe`) before writing
any parser. See the ADR-037 phase-1 commit and
`docs/learning/LEARNING-LOG.md` for the full live-verification record,
including the discovery that Sentry paginates via an RFC 5988 `Link`
header with an explicit `results="true"/"false"` flag (not GitHub's silent
per-endpoint cap), bounded here by `MAX_ISSUE_PAGES` with a typed
`SentryIncompleteResultError` if the bound is hit before `results="false"`.

### Phase 2 — Sentry↔Jira link resolution (IMPLEMENTED)

`HttpSentrySource.get_linked_jira_key(issue_id: str) -> JiraIssueKey | None`
calls a **separate, dedicated endpoint** —
`GET /organizations/{org}/issues/{issue_id}/integrations/` — verified live
against a real linked issue (Sentry org `student-whe`, issue
`PYTHON-FASTAPI-1`, linked to Jira ticket `KAN-5` via Sentry's native
"+ Link issue" action under the issue's External Links panel):

```json
[
  {
    "id": "502008",
    "provider": {"key": "jira", "slug": "jira", "name": "Jira"},
    "status": "active",
    "externalIssues": [
      {"id": "4715209", "key": "KAN-5", "url": "https://.../browse/KAN-5", ...}
    ]
  }
]
```

**Exact field path: `response[0].externalIssues[0].key`.** This was not
assumed from Sentry's general API knowledge or docs — a `pluginIssue`/
`pluginActor` field embedded directly in the ordinary issue-detail response
(`GET /organizations/{org}/issues/{issue_id}/`) was the first hypothesis
and was live-disproven: that response's complete key set (confirmed both
before and after the link existed) carries nothing Jira-related at all.
The link only ever appears via the dedicated `/integrations/` endpoint,
which is why `get_linked_jira_key` issues its own HTTP call rather than
being folded into whatever already fetches the issue.

Two multiplicity cases were explicitly decided (both unverified live — this
sandbox org only ever exercised the single-entry case) rather than assumed:

- **Multiple active integrations of different providers** (e.g. Jira +
  GitHub) in the same `/integrations/` response: filtered to
  `provider.key == "jira"` explicitly. A non-Jira integration's
  `externalIssues` is never read as a Jira key.
- **More than one Jira integration, or more than one `externalIssues` entry
  within the chosen integration**: take the first match in each case
  (`jira_integrations[0]`, `external_issues[0]`), not an error. Sentry
  documents no ordering guarantee or "primary link" flag for either list.
  This is a deliberate choice, not a discovered fact: the public return
  type (`JiraIssueKey | None`) is a single optional value, not a list, so
  *some* choice is required regardless of verification status, and the
  Phase 3 scan must not abort a whole issue over an unresolved tie between
  equally-plausible links. Revisit if a real (non-sandbox) org surfaces a
  genuine multi-link case and "first" turns out to pick the wrong one.

**Call-budget consequence for Phase 3 (flagged now per explicit request,
not to be rediscovered later):** `get_linked_jira_key` is a **second**
Sentry HTTP call per issue, on top of whatever `list_open_issues`
(itself ~1 call per ≤100 issues) and any later per-issue evidence calls
already cost. A scan capped at N issues therefore costs at least
`1 + N` Sentry calls before Phase 3 adds its own per-issue
`get_failure_location_evidence`/`get_deployment_evidence`/
`get_commit_evidence`/`get_changed_file_evidence` calls on top. Whatever
per-scan call-count cap Phase 3 introduces (the original sketch below
said "e.g. max 20") must size N against this real total, not against a
1-call-per-issue assumption.

### Phase 3 — Deterministic scan orchestrator (PLANNED, not yet built)

For each open Sentry issue (capped at N — sized per the call-budget note
above), call the existing `get_failure_location_evidence`,
`get_deployment_evidence`/`get_commit_evidence`, `get_changed_file_evidence`,
then the existing `fact_derivation/deployment.py` and `code_change.py`
functions directly as pure functions — no `AgentExecutor`, no planner.
Explicit per-issue `try`/`except` with a thin retry (not `AgentExecutor`);
one issue failing must not abort the scan. Emits a flat
`{pr, sentry_issue, jira_ticket, evidence_ids}` list.

### Phase 4 — Wire up new entry point (PLANNED, not yet built)

A new route/service method taking only `{repo}`. Does not touch the
existing planner-driven investigation path.

### Dependency (satisfied)

[ADR-036](ADR-036-commit-scoped-code-change-evidence.md) (commit-scoped
evidence without a PR) had to land first — without it, any Sentry issue
whose deployment commit has no associated PR would be silently dropped
from results. ADR-036 is Accepted and implemented.

### Bounded execution (planned, Phase 3)

No `AgentExecutor`/budget-enforcer reuse; an explicit cap on issues
processed per scan, sized against the real Sentry call count established
above (1 list call + 2 calls per issue: `get_linked_jira_key` plus at least
one more evidence call), not the originally-sketched "1 call per issue"
assumption.

## Consequences

- Two entry points, two mental models (deterministic scan vs. adaptive
  investigation) — must be documented clearly so callers pick correctly.
- Loses per-run retry/backoff from `AgentExecutor`; needs its own thin
  retry wrapper around the direct connector calls per issue.
- `fact_derivation` functions (`deployment.py`, `code_change.py`) become
  shared between both paths — any change to their signature must not break
  the planner-driven flow.
- `get_linked_jira_key`'s take-first multiplicity choice (Phase 2) is a
  correctness assumption that has not been exercised against a real
  multi-link case; see Reconsideration triggers.
- Not materially relevant: no new production dependency, no persistence
  migration, no public HTTP API yet (Phase 4 adds one), no LLM/deterministic
  boundary change within Phases 1-2 (both are pure connector-normalization
  work, same category as the rest of `sentry_http.py`).

## Invariants

- `get_linked_jira_key` never reads a non-Jira integration's
  `externalIssues` as a Jira key (`provider.key == "jira"` filter is
  mandatory, not incidental).
- `get_linked_jira_key`'s return value, when not `None`, always validates
  against `JiraIssueKey`'s existing pattern constraint — a malformed key
  from Sentry's response raises `SentryInvalidResponseError` rather than
  being silently coerced or dropped.
- `list_open_issues` never returns a partial page silently; hitting
  `MAX_ISSUE_PAGES` before Sentry's `Link` header reports
  `results="false"` raises `SentryIncompleteResultError`.
- Phases 1-2 introduce zero coupling to `AdaptiveInvestigationRuntime`,
  `TypedLLMPlanner`, or any Tool/Evidence/`InvestigationResult` type — both
  new methods return plain connector-level types
  (`SentryOpenIssue`, `JiraIssueKey | None`), not `Evidence`.

## Validation

`HttpSentrySource.list_open_issues` and `.get_linked_jira_key`: unit tests
in `tests/unit/test_sentry_http_connector.py`
(`HttpSentrySourceOpenIssuesTests`, `HttpSentrySourceLinkedJiraKeyTests`),
plus live verification against the real Sentry API (`student-whe` org) for
both methods, including the actual typed method (not just raw HTTP) for
`list_open_issues`, and both the linked (`KAN-5`) and unlinked (`None`)
cases for `get_linked_jira_key`. Full backend suite:
`uv run python -m unittest discover -s tests -v` from `services/api`
(656 passed, 0 failed, 14 skipped as of the Phase 2 commit).

## Reconsideration triggers

- If a real (non-sandbox) organization surfaces more than one active Jira
  integration, or more than one `externalIssues` entry on a single
  integration, revisit the "take first" choice in Phase 2 — verify live
  whether Sentry's ordering is actually meaningful (e.g. most-recent-first)
  before trusting it, or consider surfacing all candidates and letting
  Phase 3's caller decide instead of picking silently.
- If Phase 3's real per-scan Sentry call count (1 list + 2 per issue,
  minimum) makes the cap-per-scan number too expensive or slow in practice,
  revisit before shipping Phase 4's entry point — this was sized on paper
  here, not load-tested.
