# ADR-036: Commit-scoped code-change evidence for PR-less commits

- Status: Accepted
- Date: 2026-08-30
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

`DeterministicBaseline.investigate` ([baseline.py:141-161](../../services/api/app/investigations/baseline.py#L141-L161))
collects commit metadata for every deployment-sourced commit unconditionally
(`InvestigationToolId.GET_COMMIT`), but only collects changed-file/diff-hunk
evidence (`InvestigationToolId.GET_DIFF`) when `request.pull_request_number`
is present:

```python
if request.pull_request_number is not None:
    ...
    await self._collect_tool(evidence, missing, InvestigationToolId.GET_PULL_REQUEST, pull_request_arguments)
    await self._collect_tool(evidence, missing, InvestigationToolId.GET_DIFF, pull_request_arguments)
```

This was confirmed today by a real sandbox investigation that stalled at
`no_progress`: a deployment referenced a commit pushed directly to `main`
with no associated pull request. `GET_COMMIT` correctly returned commit
metadata (message, parents, author), but no tool existed to retrieve *what
changed* in that commit. `derive_code_failure_facts`
([code_change.py](../../services/api/app/investigations/fact_derivation/code_change.py))
never ran — it only derives from `ChangedFileEvidenceContent` and
`DiffHunkEvidenceContent`, both of which require a PR. The investigation had
commit evidence but no code-change facts, and stalled.

Confirmed against current GitHub REST docs: `GET
/repos/{owner}/{repo}/commits/{sha}` returns a `files[]` array (`filename`,
`status`, `additions`, `deletions`, `changes`, `patch`,
`previous_filename`) for a single commit, independent of any PR — the same
shape GitHub returns from `GET /pulls/{pr}/files`, which
`HttpGitHubCodeEvidenceSource` already parses via `GitHubChangedFileResponse`
([github_code_http_models.py:50-57](../../services/api/app/connectors/github_code_http_models.py#L50-L57)).
No new external capability is required, only a new call site and a new
place to put the result.

`ChangedFileEvidenceContent.pull_request_number` and
`DiffHunkEvidenceContent.pull_request_number` are both required, non-null,
`gt=0`
([models.py:143-154](../../services/api/app/investigations/models.py#L143-L154),
[models.py:209-219](../../services/api/app/investigations/models.py#L209-L219)).
Direct-to-main commit evidence cannot be represented in either type without
a schema change.

## Decision drivers

- Correctness: an investigation must be able to derive code-change facts
  from a commit alone, since not every change reaches production through a
  pull request.
- Preserve the PR-scoped path exactly as-is — zero regression risk for the
  existing, working `GET_PULL_REQUEST` / `GET_DIFF` flow.
- Evidence/content typing discipline: a consumer should never have to branch
  on "which correlation key is populated" to know what it's looking at
  (`services/api/app/investigations/CLAUDE.md`'s typed-contract and
  Evidence-vs-Fact discipline).
- Tool invocation must stay separately authorized
  (`services/api/app/tools/CLAUDE.md`) — a capability change should be
  visible as its own tool, not a silent behavior change on an existing one.
- Reuse existing normalization/patch-parsing logic
  (`_normalize_changed_file`, `_normalize_hunk`, `parse_github_patch`)
  rather than duplicating it.
- Testability: the new path must be exercisable independent of the PR path.

## Options considered

### Option A: Extend the existing content types with an optional `commit_sha`

Add `commit_sha: CommitSha | None` next to the existing
`pull_request_number` field on `ChangedFileEvidenceContent` and
`DiffHunkEvidenceContent`, and relax `pull_request_number` to optional.
Reuses one content type and one `EvidenceKind`. Every current and future
consumer of these types — fact derivation, evals, UI, any future tool —
would have to check which of the two keys is populated before it can
correlate evidence, and nothing in the type system enforces that exactly
one is set. This is exactly the hidden-branching shape the domain's typed
contracts exist to avoid.

### Option B: New parallel content types, correlated by `commit_sha`

Add `CommitChangedFileEvidenceContent` and `CommitDiffHunkEvidenceContent`
(new `EvidenceKind.COMMIT_CHANGED_FILE` / `COMMIT_DIFF_HUNK` members,
`content_type` discriminators `"commit_changed_file"` /
`"commit_diff_hunk"`), each carrying `commit_sha` as its only correlation
key — no `pull_request_number` field at all. A new connector method,
`get_commit_changed_file_evidence`, calls the single-commit endpoint and
normalizes into these types, reusing `_normalize_changed_file` /
`_normalize_hunk` internals. Fact derivation gets a second, explicit
branch correlating commit-sourced evidence by `commit_sha`, parallel to and
independent of the existing PR-number branch. Slightly more code (two
content types, two evidence kinds, one derivation branch, one tool) but
every type is unambiguous about what it means and how to correlate it.

### Option C: Fold file-diff retrieval into the existing `GET_COMMIT` tool

Have `GetCommitTool` internally also fetch and attach file/hunk evidence
whenever it runs, so no new tool is needed. Rejected: it silently changes
the behavior and cost of an existing, already-registered tool for every
current caller (baseline and any planner-generated plan referencing
`GET_COMMIT`) — a metadata-only lookup would become a metadata+diff
lookup with no way for a caller to ask for just the cheap one. That
violates "preserve existing behavior unless the task explicitly changes
it" and makes the capability change invisible at the tool-authorization
boundary.

### Option D: Resolve the commit's PR via GitHub's commit-to-PR association API and reuse the existing PR path

GitHub exposes `GET /repos/{owner}/{repo}/commits/{sha}/pulls`, listing
PRs associated with a commit. If one exists, fetch it and reuse
`get_pull_request_evidence` / `get_changed_file_evidence` unchanged.
Rejected as the primary mechanism: the motivating case is a commit with
*no* PR at all (direct-to-main), so this call would return an empty list
for exactly the case we need to fix, while adding a network round-trip and
a dependency on an association that will not exist for many production
deployments. It could later be a genuinely separate feature
(`CommitAssociatedWithPullRequestFact` already exists in
`app/investigations/models.py` for provenance linking) but does not
substitute for direct commit-diff evidence.

## Repository owner reasoning

Add `get_commit_changed_file_evidence` on `HttpGitHubCodeEvidenceSource`
using the existing single-commit `files[]` array, with no PR required,
alongside — not replacing — the existing PR-scoped methods. Represent the
result as new Evidence content types (`CommitChangedFileEvidenceContent`,
`CommitDiffHunkEvidenceContent`) correlated by `commit_sha`, not as an
extension of the PR-scoped content types with a second optional key, since
that would force every consumer to branch on which key is populated. Add
new, parallel `ChangedFileFact` / `ChangedHunkOverlapsFailureLineFact`
derivation logic that correlates on `commit_sha` when the evidence is
commit-sourced, leaving the existing PR-based correlation completely
untouched. `ChangedFileMatchesFailureFileFact` needs no change — its
path-only comparison already works against either evidence source.

## Reasoning review

Option B is the only option that keeps the PR path's blast radius at zero
and keeps every content type's correlation key unambiguous, matching the
domain's existing typed-contract discipline (it also matches the shape
`ADR-021` already chose: three separate single-purpose connector
operations rather than one generalized one). `ChangedFileFact` already
declares `pull_request_number` as nullable with a comment anticipating
non-PR-linked sources
([models.py:359-366](../../services/api/app/investigations/models.py#L359-L366)),
so the *fact* schema requires no change — only new *evidence* content
types and a second derivation branch that produces the same fact types.
One nuance worth flagging: registering the new tool in `TOOL_DEFINITIONS`
makes it visible to any planner enumerating that list (the LLM planner in
`app/investigations/planning` included, per `ADR-022`'s static-plan-output
contract), but *fixing the stalled investigation* also requires wiring an
unconditional call into `DeterministicBaseline` for every deployment-sourced
commit — registration alone does not make the deterministic baseline call
it. Both are in scope below.

## Decision

Add commit-scoped code-change evidence, additive and parallel to the
existing PR-scoped path:

1. **Connector**: `HttpGitHubCodeEvidenceSource.get_commit_changed_file_evidence(GitHubCommitEvidenceRequest) -> tuple[Evidence, ...]`, calling `GET /repos/{owner}/{repo}/commits/{sha}` and reading its `files[]`. `GitHubCommitEvidenceResponse` gains a `files: list[GitHubChangedFileResponse]` field (the existing model is reused as-is); `get_commit_evidence` ignores it, the new method uses it. Reuses `_normalize_changed_file` / `_normalize_hunk` / `parse_github_patch`, adapted to emit the new content types.
2. **Evidence**: new `EvidenceKind.COMMIT_CHANGED_FILE` / `COMMIT_DIFF_HUNK`; new `CommitChangedFileEvidenceContent` (`commit_sha`, `path`, `change_type`, `previous_path`, `additions`, `deletions`, `changes`, `patch_available`) and `CommitDiffHunkEvidenceContent` (`commit_sha`, `file_path`, `old_start`, `old_count`, `new_start`, `new_count`, `lines`) added to the `EvidenceContent` union.
3. **Fact derivation**: `code_change.py` gains a second branch, parallel to the existing one, correlating `CommitChangedFileEvidenceContent` / `CommitDiffHunkEvidenceContent` by `commit_sha` instead of `pull_request_number`, producing the same `ChangedFileFact` / `ChangedHunkOverlapsFailureLineFact` types (with `pull_request_number=None`). `ChangedFileMatchesFailureFileFact` derivation is untouched.
4. **Tool**: new `InvestigationToolId.GET_COMMIT_DIFF`, `ToolDefinition(input_model=GitHubCommitEvidenceRequest, plan_output_model=GetCommitDiffPlanOutput)`, and `GetCommitDiffTool` in `app/tools/adapters.py`, mirroring `GetDiffTool` but calling the new connector method.
5. **Baseline wiring**: `DeterministicBaseline` calls `GET_COMMIT_DIFF` for every deployment-sourced `commit_sha` (same loop that already calls `GET_COMMIT`, [baseline.py:141-152](../../services/api/app/investigations/baseline.py#L141-L152)), unconditional on `request.pull_request_number` — this is the specific change that fixes the stalled-investigation case, since a deployment's commit and a request's referenced PR are independent facts and either, both, or neither may be present.

The existing `GET_COMMIT`, `GET_PULL_REQUEST`, and `GET_DIFF` tools,
`ChangedFileEvidenceContent`, `DiffHunkEvidenceContent`, and their
derivation branch are not modified.

## Implementation update (2026-09-08)

**IMPLEMENTED**, all five decision items, in four commits each verified by
the full backend test suite (`uv run python -m unittest discover -s tests -v`,
643 tests, 0 failures) before proceeding to the next: (1) connector method
+ evidence content types, (2) fact-derivation branch, (3) `GET_COMMIT_DIFF`
tool + fakes, (4) unconditional baseline wiring. The `files[]` shape this
ADR's Context section claims was re-verified live (not from the ADR's own
memory of it) by calling `GET /repos/{owner}/{repo}/commits/{sha}`
unauthenticated against this repository's own public GitHub mirror before
any code was written — confirmed identical to `GitHubChangedFileResponse`'s
existing fields, with an unpaginated ~300-file cap this ADR did not address
and which remains out of scope. `test_evidence_models.py`'s
`test_each_initial_source_kind_content_pair_is_valid` — an exhaustiveness
check over every `EvidenceKind` member — required updating; it is the kind
of consumer this ADR anticipated ("every current and future consumer...
would have to check which of the two keys is populated," Option A's
rejection) and validates that Option B's two new kinds were wired
correctly rather than silently skipped. A new
`test_direct_to_main_commit_without_pull_request_still_derives_code_facts`
in `test_deterministic_baseline.py` directly proves the motivating bug is
fixed: a deployment with `pull_request_number=None` now produces
`changed_file` facts where it previously produced none.

## Consequences

- A direct-to-main commit now produces `ChangedFileFact` /
  `ChangedHunkOverlapsFailureLineFact` evidence and facts even with no PR,
  fixing the class of stall observed today.
- Two new Evidence content types and two new `EvidenceKind` members
  permanently widen the domain vocabulary — this is the accepted cost of
  avoiding a shared, ambiguous key.
- When both a deployment commit and a request-level PR number are present,
  an investigation may now issue both a commit-diff and a PR-diff call;
  they are independent and may reference different commits, so no
  deduplication is implied or required.
- No change to GitHub authentication, rate-limit behavior, or credential
  handling — same connector, same settings, one additional read-only
  endpoint.
- No production dependency, persistence migration, public API, or
  deployment change. No LLM/deterministic boundary change — this is
  evidence collection and deterministic fact derivation throughout.

## Invariants

- `CommitChangedFileEvidenceContent` and `CommitDiffHunkEvidenceContent`
  carry `commit_sha` and never `pull_request_number`; `ChangedFileEvidenceContent`
  and `DiffHunkEvidenceContent` are unchanged and still require
  `pull_request_number`.
- Fact derivation never mixes a commit-sourced changed file with a
  PR-sourced hunk (or vice versa) when matching hunks to files.
- `Evidence.kind.value == Evidence.content.content_type` continues to hold
  for the two new content types (per the existing validator at
  [models.py:337-339](../../services/api/app/investigations/models.py#L337-L339)).
- `get_commit_changed_file_evidence` never returns raw GitHub JSON or HTTP
  objects; same validation/pagination/error taxonomy as the existing
  connector methods.
- The new tool is read-only and subject to the same per-invocation
  authorization as every other tool.

## Validation

New/updated unit tests: `test_github_code_http.py` (new connector method,
response parsing, patch/hunk normalization), `test_github_code_evidence_contracts.py`,
`test_evidence_models.py` (new content types, kind/content-type agreement),
a fact-derivation test covering the commit-sourced branch (extending
coverage currently in `test_code_diagnosis.py` / `test_investigation_models.py`
/ `test_relationship_index.py`), `test_tool_registry.py` (new tool
definition), and `test_deterministic_baseline.py` (unconditional
`GET_COMMIT_DIFF` call). New fixtures in `github_fixtures.py` and a new
fake method in `github_code_fakes.py`. Existing PR-scoped tests must pass
unchanged, proving zero regression on that path. Full backend suite:
`uv run python -m unittest discover -s tests -v` from `services/api`.

## Reconsideration triggers

Revisit if a real workflow needs to correlate a commit-sourced change back
to a PR after the fact (e.g., a squash-merge later associates the commit
with a PR) — that is a separate concern already partially represented by
`CommitAssociatedWithPullRequestFact` and is deferred, not solved, here.
Revisit the two-content-type split if a third correlation key (e.g. a
branch ref) emerges and the parallel-branch pattern starts duplicating
too much derivation logic to justify per-source types.
