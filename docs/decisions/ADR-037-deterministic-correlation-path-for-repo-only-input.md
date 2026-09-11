# ADR-037: Deterministic correlation path for repo-only input

- Status: Accepted (all four phases decided and implemented)
- Date: 2026-09-08
- Owners: Repository owner
- Supersedes: None
- Superseded by: None
- Amended by: [ADR-038](ADR-038-grounded-reasoning-for-the-deterministic-correlation-scan.md)
  — the "no hypothesis, no rendering through `render_grounded_result`"
  sentence in the Decision section below is superseded; the "zero coupling
  to `AdaptiveInvestigationRuntime`/`TypedLLMPlanner`" invariant is
  unchanged and still holds. Kept below unedited per this repo's "never
  rewrite an accepted historical ADR" convention.

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

### Phase 3 — Deterministic scan orchestrator (IMPLEMENTED)

`app/workflows/correlation_scan.py`'s `scan_repository_for_correlations`
implements the orchestrator, with two material corrections to this ADR's
original sketch, both found live rather than assumed:

**`get_deployment_evidence` is not called at all — replaced by a new
`HttpSentrySource.get_issue_commit_sha(issue_id) -> CommitSha | None`.**
A bare Sentry issue never exposes a single `"version:environment"` string
`get_deployment_evidence` requires (only a tag *facet count*, e.g.
`{"key":"environment","totalValues":2}`, never the value itself), and this
sandbox's real release data has `lastCommit: null` regardless — so even a
successful environment resolution would still fail with
`SentryReleaseMissingCommitError`. `get_issue_commit_sha` instead reuses
`_resolve_issue`'s existing single call to the issue-detail endpoint (no
dedicated call needed — verified live that the issue-detail response
already embeds the *full* release object, including `lastCommit`, not just
a version string) and: (1) returns `firstRelease.lastCommit.id` when
Sentry tracked one; (2) otherwise falls back to `firstRelease.version`
itself, **only** when it already matches `CommitSha`'s exact shape
(shape-validated, never assumed); (3) otherwise `None`. Both real sandbox
issues resolve via the fallback path (`firstRelease.lastCommit` is `null`
for both; `firstRelease.version` happens to already be a raw commit SHA
in this sandbox's release-tracking setup).

**Call sequence, as actually built (per issue):**
```
get_failure_location_evidence(incident_reference=issue.issue_id)  — Sentry
get_linked_jira_key(issue.issue_id)                                — Sentry (Phase 2)
get_issue_commit_sha(issue.issue_id)                                — Sentry (new)
if commit_sha:
  get_commit_evidence(owner, name, commit_sha)                     — GitHub
  get_commit_changed_file_evidence(owner, name, commit_sha)        — GitHub (ADR-036)
derive_deployment_code_facts(evidence)  — pure; () here, no DeploymentEvidenceContent ever gathered
derive_code_failure_facts(evidence)     — pure; the real per-issue fact output
```

**Per-scan cap: `MAX_ISSUES_PER_SCAN = 5`** (lowered from this ADR's
original "e.g. max 20" sketch — at up to ~4 Sentry + 2 GitHub calls per
issue, 20 issues risked real rate-limit/cost exposure before the
orchestrator had been proven correct even once; raise later once verified
against real, higher-volume data). Applied by slicing
`open_issues[:max_issues]` *before* the per-issue loop starts, never as an
afterthought. Non-silent: `RepositoryCorrelationScanResult` carries
`total_open_issues_found`, `issues_scanned`, and `truncated: bool`
explicitly, the same principle as flagging GitHub's file-list cap below
rather than hiding either.

**Per-issue failure isolation:** each connector call in `_correlate_issue`
is wrapped individually by `_call_step`, a thin, single retry — exactly
one retry, only for the same retryable category set `ToolFailure.retryable`
already defines (`RATE_LIMITED`/`TIMEOUT`/`UPSTREAM_UNAVAILABLE`), no
backoff — not `AgentExecutor`/`RetryPolicy`. A failed step is recorded as a
typed `StepFailure(step, failure_code)` and the loop continues; evidence
already collected from earlier-succeeding steps is never discarded because
a later step failed. `list_open_issues` (the scan's bootstrapping call) is
deliberately *not* wrapped this way — if the scan can't even list issues,
returning an empty result would misrepresent "provider unavailable" as
"zero open issues," so that failure is allowed to propagate.

**A real, load-bearing ambiguity this design resolves explicitly:** a
`None` `jira_ticket` is ambiguous on its own — "confirmed no link" and
"lookup failed" both produce `None`. `step_failures` disambiguates: a
`LINKED_JIRA_KEY` entry there means the lookup failed (link status
unknown), its absence with `jira_ticket=None` means Sentry confirmed no
link exists.

**GitHub's ~300-file silent cap (deferred in ADR-036, decided here):** a
cheap, no-extra-call heuristic —
`possibly_truncated_file_list: bool = (changed_file_count == 300)` per
issue. Imperfect (a commit could legitimately touch exactly 300 files) but
it is the only signal GitHub's API offers, and surfacing a heuristic beats
staying silent about it.

**Output contract, as built** (`IssueCorrelationResult`): `sentry_issue_id`,
`sentry_short_id`, `jira_ticket: JiraIssueKey | None`,
`commit_sha: CommitSha | None`, `pull_request_number: int | None` (always
`None` on this path — kept for shape parity with the PR-scoped facts the
same `derive_code_failure_facts` also knows how to produce, and for a
possible future PR-resolution phase), `evidence_ids`, `fact_ids` (addition
beyond this ADR's original `{pr, sentry_issue, jira_ticket, evidence_ids}`
sketch), `possibly_truncated_file_list`, `status`
(`ok`/`partial`/`failed`), `step_failures`.

### Phase 4 — Wire up new entry point (IMPLEMENTED)

`POST /v1/correlation-scans` (`app/api/v1/correlation_scan_router.py`).
Three design decisions were made explicitly before implementation (per the
Level-2 process — a new HTTP route is a public API/schema change), not
assumed:

- **Request body is not `{repo}`-only.** The original sketch above said
  "a route taking only `{repo}`," but `scan_repository_for_correlations`
  genuinely needs `sentry_project_slug` as an independent, required field —
  proven by this ADR's own Phase 3 correction (`promptql` vs.
  `promptql-sandbox`, a Sentry project whose commits live in a differently-
  named repo). `CorrelationScanRequest` requires
  `repository_owner`/`repository_name`/`sentry_project_slug` explicitly;
  none is derived from another.
- **Requires an authenticated user with their own connected Sentry and
  GitHub credentials — no anonymous/demo fallback.** Unlike
  `get_incident_source`/`get_github_code_evidence_source`
  (`connector_router.py`), which fall back to `app.state`'s fake/demo
  sources for anonymous callers, `list_open_issues`/`get_linked_jira_key`/
  `get_issue_commit_sha` have no fake equivalent (deliberately, Phases
  1-2), so there is nothing to fall back to. A new
  `get_sentry_source_for_scan` dependency returns a clean `409` for an
  anonymous or demo caller, or one with no stored Sentry credential.
- **Synchronous, not async/SSE like `POST /v1/investigations`.** The scan
  makes zero LLM calls and is bounded (≤~35 external calls at
  `MAX_ISSUES_PER_SCAN = 5`); the existing async/SSE run-lifecycle
  machinery exists specifically for unpredictable LLM planning latency,
  which does not apply here. The route returns the full
  `RepositoryCorrelationScanResult` directly in the response body.

**A real testability gap found and fixed while building this, not
inherited silently:** `connector_router.py`'s existing `get_incident_source`
et al. call `get_credential_repository(request)` as a plain function, not
`Depends(get_credential_repository)` — meaning `app.dependency_overrides`
cannot intercept it, since overrides only affect `Depends()`-injected
parameters. `get_sentry_source_for_scan` uses a real `Depends()` parameter
instead, matching `credentials_router.py`'s own testable pattern rather
than copying the untestable one forward into new code. The existing
functions were not changed — this is a local, contained choice for new
code, not a fix to pre-existing routes.

`SentryConnectorError` from the one call `scan_repository_for_correlations`
does not isolate (`list_open_issues` itself) is caught at the route and
mapped to a typed `ApiError` (`CORRELATION_SCAN_UPSTREAM_FAILED`), `503`
for the same retryable-shaped categories `_call_step` already treats as
retryable plus `CONFIGURATION_ERROR`, `502` otherwise. Every per-issue
failure inside the scan is already isolated into `step_failures` and never
reaches the route as an exception.

### Dependency (satisfied)

[ADR-036](ADR-036-commit-scoped-code-change-evidence.md) (commit-scoped
evidence without a PR) had to land first — without it, any Sentry issue
whose deployment commit has no associated PR would be silently dropped
from results. ADR-036 is Accepted and implemented.

### Bounded execution (IMPLEMENTED)

No `AgentExecutor`/budget-enforcer reuse. `MAX_ISSUES_PER_SCAN = 5`,
applied before fan-out, with an explicit non-silent `truncated` flag — see
Phase 3 above.

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
- `derive_deployment_code_facts` is called in the Phase 3 chain but
  currently always returns `()`, since no `DeploymentEvidenceContent` is
  ever gathered on this path (deliberately — see Phase 3's
  `get_deployment_evidence` explanation). Kept for forward-compatibility,
  not dead code by design — it would activate automatically if a future
  revision ever adds deployment evidence to this evidence set.
- `MAX_ISSUES_PER_SCAN = 5` is conservative and will need raising once the
  orchestrator is exercised against a higher-issue-count project; the real
  per-issue call count (up to 4 Sentry + 2 GitHub) is now measured, not
  estimated, so a future increase can be sized against real data.
- Not materially relevant: no new production dependency, no persistence
  migration, no public HTTP API yet (Phase 4 adds one), no LLM/deterministic
  boundary change within Phases 1-3 (all pure connector-normalization and
  deterministic orchestration, same category as the rest of
  `sentry_http.py`/`fact_derivation`).

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
- Phases 1-3 introduce zero coupling to `AdaptiveInvestigationRuntime`,
  `TypedLLMPlanner`, or any Tool/Evidence/`InvestigationResult` type —
  `scan_repository_for_correlations` returns `RepositoryCorrelationScanResult`,
  a plain workflow-level type, never an `InvestigationResult`.
- A `None` `jira_ticket` alone never distinguishes "confirmed no link" from
  "lookup failed" — callers must check `step_failures` for a
  `ScanStep.LINKED_JIRA_KEY` entry to tell them apart.
- One issue's connector failure never aborts the scan; `list_open_issues`
  failing does (see Phase 3's "Per-issue failure isolation" above).
- The per-issue cap is applied before fan-out; a truncated scan is always
  reported via `RepositoryCorrelationScanResult.truncated`, never silent.

## Validation

`HttpSentrySource.list_open_issues`, `.get_linked_jira_key`,
`.get_issue_commit_sha`: unit tests in `tests/unit/test_sentry_http_connector.py`
(`HttpSentrySourceOpenIssuesTests`, `HttpSentrySourceLinkedJiraKeyTests`,
`HttpSentrySourceIssueCommitShaTests`). `scan_repository_for_correlations`:
`tests/unit/test_correlation_scan.py` (`CorrelationScanTests` — ok/partial
status, confirmed-unlinked vs. lookup-failed disambiguation, GitHub-not-found
handled as partial not a crash, no-resolvable-commit skips GitHub entirely,
cap-before-fan-out with the non-silent `truncated` flag, the 300-file
heuristic, and the single thin retry actually retrying exactly once).
`POST /v1/correlation-scans`: `tests/integration/test_correlation_scan_api.py`
(`CorrelationScanApiTests` — anonymous/demo/no-credential all `409` before
any connector call, missing `sentry_project_slug` rejected as `422`, a
`SentryConnectorError` from `list_open_issues` mapped to the typed
`ApiError`, and a full successful scan's response shape). Full backend
suite: `uv run python -m unittest discover -s tests -v` from `services/api`
(676 passed, 0 failed, 14 skipped as of the Phase 4 commit).

Live end-to-end, the real `HttpSentrySource` and `HttpGitHubCodeEvidenceSource`
together (not mocked), against both real sandbox issues:

- **`python-fastapi` project (issue `PYTHON-FASTAPI-1`)**: first run
  produced `jira_ticket: "KAN-5"`, `commit_sha: "e1448f6171fd..."`
  (resolved via the `firstRelease.version` fallback — Sentry's
  `lastCommit` was `null`), `status: "partial"` —
  `commit_evidence`/`commit_changed_file_evidence` both failed (GitHub's
  real response was `422`). **Corrected 2026-09-10**: that `422` was not
  a genuinely-unpushed commit — the verification script was pointed at
  the wrong repo (`banalasaisathwik/promptql`). The commit is real and
  exists in `banalasaisathwik/promptql-sandbox`, the app's actual
  deployed source; re-run against the correct repo gives `status: "ok"`,
  one changed file, one hunk, one `changed_file` fact, and the commit's
  message/changed file directly match the crash frame. See
  Reconsideration triggers for the resulting design finding (the fallback
  is shape- not existence-validated) and the `COMMIT_NOT_FOUND` mapping
  this prompted. `evidence_ids` in the original `"partial"` run still
  contained the successful failure-location evidence even though the
  GitHub steps failed — proving a later step's failure does not discard
  earlier-succeeding evidence, independent of which repo was queried.
- **`python-flask` project (issue `PYTHON-FLASK-1`)**: `jira_ticket: null`
  (confirmed unlinked — no `LINKED_JIRA_KEY` entry in `step_failures`,
  correctly distinguished from a lookup failure), `commit_sha:
  "c88b0693..."` (same fallback path, and this SHA *is* real on GitHub),
  `status: "ok"`, 86 evidence IDs (1 failure-location + 1 commit + ~30
  changed files + ~54 diff hunks) and 31 `changed_file` facts derived —
  `possibly_truncated_file_list: false` (well under 300). No
  `changed_hunk_overlaps_failure_line` facts, expected: this real commit
  in the `promptql` repo is unrelated to the sandboxed Flask app's crash
  site, so no hunk overlaps the failure-location's line — a correct
  "no fact" outcome, not a bug.

## Reconsideration triggers

- If a real (non-sandbox) organization surfaces more than one active Jira
  integration, or more than one `externalIssues` entry on a single
  integration, revisit the "take first" choice in Phase 2 — verify live
  whether Sentry's ordering is actually meaningful (e.g. most-recent-first)
  before trusting it, or consider surfacing all candidates and letting
  Phase 3's caller decide instead of picking silently.
- If the real per-scan call count (1 Sentry list + up to 4 Sentry + 2
  GitHub per issue) makes `MAX_ISSUES_PER_SCAN = 5` too slow or expensive
  in practice, or too conservative once correctness is well-established,
  revisit the cap before or shortly after shipping Phase 4's entry point.
- **Correction to the entry above, found 2026-09-10**: the `PYTHON-FASTAPI-1`
  `"partial"` case was not a genuinely-unpushed commit. `e1448f6171fd...`
  is real, and exists in a *different* repository
  (`banalasaisathwik/promptql-sandbox`, not `banalasaisathwik/promptql`) —
  the actual deployed source for that Sentry project's sandbox app. The
  end-to-end verification script was pointed at the wrong repo. Re-run
  against the correct repo: `status: "ok"`, one changed file, one hunk,
  one `changed_file` fact, from a commit whose message and sole changed
  file (`sandbox-target/app/checkout.py`) directly match the crash frame.
  Genuinely-unpushed commits producing `"partial"` remains a real,
  separate possibility worth revisiting if it turns out common in
  practice — see the next trigger for why the two causes are currently
  indistinguishable in the result.
- **`get_issue_commit_sha`'s fallback is shape-validated only, never
  existence-validated against the specific repo a scan targets.** When
  `firstRelease.lastCommit` is null, the fallback trusts
  `firstRelease.version` as a commit SHA purely because it matches
  `CommitSha`'s regex — it has no way to confirm that SHA actually exists
  in `repository_owner`/`repository_name`, because nothing in Sentry's API
  ties a project to a specific GitHub repository. `repository_owner`,
  `repository_name`, and `sentry_project_slug` are three independent
  caller-supplied inputs to `scan_repository_for_correlations`, and
  nothing validates that they name the same deployed app. Found live,
  the hard way: the very `PYTHON-FASTAPI-1` mismatch above was caused by
  exactly this — pairing `sentry_project_slug="python-fastapi"` with the
  wrong repo produced a confident-looking `commit_sha` that then failed
  at the GitHub step. This is the caller's responsibility to get right;
  the scan cannot detect the mismatch itself, and a mismatch is
  observationally identical (until the 2026-09-10 fix directly below) to
  "this issue's commit genuinely hasn't been pushed yet" — both produced
  `status: "partial"` with the same generic GitHub failure code. Revisit
  if Phase 4 needs to actively guard against this (e.g. a configured
  Sentry-project-to-repo mapping checked before scanning) rather than
  leaving it purely on the caller.
- **Partially addressed 2026-09-10**: `github_http_base.py`'s
  `_raise_for_status` now maps GitHub's `422` (returned for "no commit
  found for this SHA") to a distinct `COMMIT_NOT_FOUND` category instead
  of the generic `INVALID_RESPONSE` catch-all — see
  `GitHubCommitNotFoundError`. This makes "commit doesn't exist in this
  repo" distinguishable from other invalid-response causes in
  `step_failures`, but does not by itself distinguish "wrong repo" from
  "not pushed yet" — both are still `COMMIT_NOT_FOUND` from the scan's
  point of view, since neither Sentry nor GitHub's API can tell those two
  apart without the mapping above.
