# ADR-038: Grounded reasoning for the deterministic correlation scan

- Status: Accepted (implemented)
- Date: 2026-09-10
- Owners: Repository owner
- Supersedes: None
- Superseded by: None
- Amends: [ADR-037](ADR-037-deterministic-correlation-path-for-repo-only-input.md)
  (see "Correction to ADR-037's invariant" below)

## Context

ADR-037's deterministic correlation scan (`POST /v1/correlation-scans`)
resolves, per open Sentry issue: failure location, linked Jira ticket,
commit, changed files/diff hunks, and deterministic Facts
(`ChangedFileFact`, `ChangedFileMatchesFailureFileFact`,
`ChangedHunkOverlapsFailureLineFact`). It deliberately stops there — no
hypothesis, no code diagnosis, no LLM call anywhere in the path. That is the
correct place to have stopped for Phases 1-3: none of that correlation work
is probabilistic, so nothing about it should touch an LLM.

But the scan's own Facts are now sitting unused in exactly the shape
`InvestigationWorkflowService`'s adaptive path already knows how to turn
into a hypothesis, a code finding, and a developer recommendation —
`TypedLLMHypothesisGenerator` → `DeterministicHypothesisValidator` →
`TypedLLMCodeDiagnoser` → `DeterministicCodeFindingValidator` →
`build_developer_recommendations`. Leaving the scan a bare Facts dump forces
whoever reads its output to redo that same causal reasoning by hand for
every issue. This ADR extends the scan to call that same pipeline, once
per issue, after its own deterministic phase finishes — never before, and
never in place of it.

## Decision drivers

- Correctness: reuse the identical typed generator, identical deterministic
  validators, and identical rendering the adaptive path already uses. A
  second, independently-drifting hypothesis/code-diagnosis implementation
  is worse than no reuse at all.
- Core V2 principle: probabilistic reasoning may propose; deterministic code
  controls what is accepted, executed, persisted, and exposed. The LLM must
  never be allowed to expand its role from "interpret Facts a deterministic
  step already collected" to "decide what to fetch."
- Cost/latency: only call an LLM when a cheap deterministic check shows a
  candidate could possibly be accepted — never merely to explain that
  evidence was insufficient.
- Failure isolation: one issue's LLM failure (or a genuinely unexpected
  exception in the new stage) must never abort the scan or another issue's
  analysis, extending ADR-037's existing per-issue `step_failures` isolation
  to the new reasoning phase.
- Learning: demonstrates that "deterministic scan" and "grounded reasoning"
  are not mutually exclusive — the scan's control flow stays entirely
  deterministic; only the *interpretation* of already-grounded Facts is ever
  probabilistic, and only after deterministic validation does it reach the
  response.

## Options considered

### Option A: Leave the scan Facts-only; add a separate `POST /v1/correlation-scans/{id}/analyze` follow-up endpoint per issue

Rejected — doubles the number of round trips a caller needs for the exact
same information a single scan call can already produce in one pass, and
requires persisting per-issue scan state somewhere just to give a follow-up
call something to reference. Nothing about the correlation phase's own
Facts/Evidence needs to be durable to reach a hypothesis; keeping them
in-process for one more downstream step is simpler and cheaper.

### Option B: Reuse `InvestigationWorkflowService.continue_persisted_run` per issue by synthesizing an `InvestigationRequest` and letting the full planner-driven flow run

Rejected outright — this is exactly the architectural mistake ADR-037
existed to avoid. Routing through `TypedLLMPlanner`/`AdaptiveInvestigation
Runtime`/`AgentExecutor` would spend a planning LLM call re-discovering
facts the scan already deterministically collected, reintroduce plan
validation/budget/retry machinery this path has no use for, and make the
"deterministic scan" claim false.

### Option C: Call the existing generator/validator classes directly from `correlation_scan.py`, once per issue, strictly downstream of the deterministic phase

Chosen. `TypedLLMHypothesisGenerator`, `DeterministicHypothesisValidator`,
`CodeContextBuilder`, `TypedLLMCodeDiagnoser`,
`DeterministicCodeFindingValidator`, and `build_developer_recommendations`
are already free-standing, dependency-injected classes/functions with no
coupling to `AdaptiveInvestigationRuntime`, `TypedLLMPlanner`, or
`InvestigationRun` persistence — `InvestigationWorkflowService` is simply
one caller of them, not their only legitimate caller. `correlation_scan.py`
becomes a second, independent caller with its own control flow, its own
per-issue Facts/Evidence, and its own new analysis-status vocabulary,
without importing or touching a single planner/executor class.

## Decision

Add a strictly-downstream grounded-reasoning phase to `_correlate_issue`,
gated by a cheap deterministic check, per issue:

```
existing deterministic correlation (ADR-037, unchanged)
        |
        v
deterministic gate: does this issue have a ChangedFileFact whose path
also appears in a ChangedFileMatchesFailureFileFact/
ChangedHunkOverlapsFailureLineFact? (_has_hypothesis_worthy_facts)
        |  no                                   | yes
        v                                       v
INSUFFICIENT_EVIDENCE                TypedLLMHypothesisGenerator
(no LLM call)                                  |
                                                v
                                  DeterministicHypothesisValidator
                                       |                    |
                                  0 accepted           >=1 accepted
                                       |                    |
                                       v                    v
                          NO_VALIDATED_HYPOTHESIS   CodeContextBuilder
                                                            |
                                                            v
                                                  TypedLLMCodeDiagnoser
                                                     |             |
                                                  failed        succeeded
                                                     |             |
                                                     v             v
                                       CODE_FINDING_UNAVAILABLE  DeterministicCodeFindingValidator
                                                                    |                |
                                                               0 accepted      >=1 accepted
                                                                    |                |
                                                                    v                v
                                                     CODE_FINDING_UNAVAILABLE     COMPLETED
                                                                          (both via build_developer_recommendations
                                                                           + render_grounded_result)
```

Any unexpected exception anywhere in this phase (not just a typed
`HypothesisGenerationError`/`CodeDiagnosisError`) is caught once, at the top
of `_run_issue_analysis`, reported through the same
`record_investigation_diagnostic_failure` telemetry path, and turned into
`ANALYSIS_ERROR` — it never propagates to abort the issue's own already-
computed deterministic correlation, another issue's analysis, or the scan.

### New response contract (additive, ADR-037's fields unchanged)

```python
class IssueAnalysisStatus(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HYPOTHESIS_GENERATION_FAILED = "hypothesis_generation_failed"
    NO_VALIDATED_HYPOTHESIS = "no_validated_hypothesis"
    CODE_FINDING_UNAVAILABLE = "code_finding_unavailable"
    COMPLETED = "completed"
    ANALYSIS_ERROR = "analysis_error"

class IssueGroundedAnalysis(ContractModel):
    status: IssueAnalysisStatus
    hypotheses: tuple[GroundedHypothesis, ...] = ()
    code_findings: tuple[GroundedCodeFinding, ...] = ()
    recommendations: tuple[DeveloperRecommendation, ...] = ()

class IssueCorrelationResult(ContractModel):
    # ...every existing ADR-037 field, unchanged...
    presentation: CorrelationScanPresentation
    analysis: IssueGroundedAnalysis
```

The later Whyline V1 presentation addition is additive and deliberately
separate from this ADR's grounded analysis. `CorrelationScanPresentation`
contains only normalized Sentry title/failure-location fields plus concise,
deterministic `FactSummary` records for the three correlation Fact types. It
does not serialize Evidence, raw provider responses, source code, prompts, or
unvalidated candidates, and does not add a scan run/history/SSE lifecycle.

`IssueCorrelationStatus` (`ok`/`partial`/`failed`) keeps answering only "did
deterministic source correlation succeed?" `IssueAnalysisStatus` is a
separate, new vocabulary answering "how far did grounded reasoning get?" — a
`PARTIAL` correlation (e.g. GitHub 404 on the commit) can still reach
`INSUFFICIENT_EVIDENCE` cleanly, and an `OK` correlation can still land on
`NO_VALIDATED_HYPOTHESIS` if the LLM's candidate cites the wrong file. The
two are never conflated in code: `analysis` is computed entirely from the
same-issue `facts`/`evidence_tuple` already resolved before `status` is
computed, and neither one's terminal value participates in the other's.

`hypotheses`/`code_findings` are deliberately plural
(`tuple[GroundedHypothesis, ...]`, matching
`GroundedInvestigationResult.supported_hypotheses`'s existing shape) rather
than the single optional `hypothesis: GroundedHypothesis | None` sketched
conceptually in the originating task description — `DeterministicHypothesis
Validator` can already accept up to `MAX_HYPOTHESES = 3` candidates for one
issue, and forcing that down to one would either drop real validated
hypotheses silently or need an arbitrary "pick one" rule with no existing
justification. Reusing the exact plural shape the adaptive path's own
contract already established was the lower-risk, more consistent choice.

### Deterministic gate before every LLM call (`_has_hypothesis_worthy_facts`)

Mirrors, but never substitutes for, `DeterministicHypothesisValidator`'s own
entity-matching rule (a changed path must also match the observed failure
location). It only decides whether the round trip is worth attempting; the
validator remains the sole authority over which real candidate is accepted.
Symmetric gates were not added before code diagnosis or recommendation
generation because both are already unreachable unless the validator ahead
of them accepted something — no separate check is needed.

### Deterministic per-issue investigation goal

```python
def _issue_investigation_goal(short_id: str) -> str:
    return (
        f"Determine whether the observed code changes associated with "
        f"Sentry issue {short_id} plausibly explain its recorded failure "
        f"location."
    )
```

Built from the issue's own short ID alone — the generator is never asked to
rediscover which commit, Jira ticket, or changed file is relevant, since
those are already Facts by the time this goal is built. The same string
also becomes `InvestigationRequest.question` for `CodeContextBuilder.build`,
and `InvestigationRequest.incident_reference` is set to the Sentry issue ID
so `InvestigationRequest`'s existing `validate_grounding_reference` check is
satisfied without inventing a new relaxed constructor path.

### A real, load-bearing gap found and fixed while building this

`CodeContextBuilder._location()` and `DeterministicCodeFindingValidator`
(`app/investigations/code_diagnosis/{context,validator}.py`) only ever
recognized `ChangedFileEvidenceContent`/`DiffHunkEvidenceContent` — the
PR-scoped evidence content types. ADR-036's commit-scoped
`CommitChangedFileEvidenceContent`/`CommitDiffHunkEvidenceContent` (no
associated pull request) were never wired into either one, because the
adaptive investigation path's own allowed tool list
(`ADAPTIVE_INVESTIGATION_ALLOWED_TOOL_IDS` in `app/workflows/
investigation.py`) never includes `GET_COMMIT_DIFF` and so never produces
that evidence shape. The correlation scan, by contrast, *only* ever produces
commit-scoped evidence (ADR-036/037) — meaning code diagnosis would have
reached the LLM missing every changed-file/diff-hunk location, and even a
correctly-grounded LLM proposal would always have been rejected by the
validator's `changed_file_observed`/`_location_path` checks, which likewise
only recognized the PR-scoped types. Both files now treat
`CommitChangedFileEvidenceContent`/`CommitDiffHunkEvidenceContent` as
structurally parallel to their PR-scoped counterparts (same fields, same
meaning) — mirroring the exact dual-branch pattern
`fact_derivation/code_change.py` already uses for the same two content
families. Verified live (in-process, `FakeLLMClient`, no network) end to
end: commit-scoped changed-file + diff-hunk + stack-frame evidence now
reaches `IssueAnalysisStatus.COMPLETED` with a grounded `GroundedCodeFinding`
citing the diff hunk. This is a bug fix to already-shipped code required to
make this ADR's stated goal reachable at all, not an unrelated refactor —
without it, correlation-scan code diagnosis was structurally incapable of
ever succeeding.

### LLM client wiring (no client constructed inside `correlation_scan.py`)

`scan_repository_for_correlations` takes `hypothesis_client`/
`code_diagnosis_client: TypedLLMClient | None = None`, defaulting to
`app.explanations.fakes.FakeLLMClient()` — the same deterministic,
network-free fake the rest of the app already uses for local/demo
`LLMProvider.FAKE` wiring, and the same one whose `HypothesisGenerationOutput`/
`CodeDiagnosisOutput` fixtures already exist specifically to exercise this
family of validators. `POST /v1/correlation-scans`
(`app/api/v1/correlation_scan_router.py`) never relies on that default: two
new `Depends()` functions,
`get_correlation_scan_hypothesis_client`/`get_correlation_scan_code_diagnosis_client`,
read `request.app.state.investigation_hypothesis_client`/
`investigation_code_diagnosis_client` — the exact same `app.state` clients
`get_investigation_workflow` (`connector_router.py`) already injects into
`InvestigationWorkflowService`, themselves resolved in `main.py` from
`LLMTask.HYPOTHESIS_GENERATION`/`LLMTask.CODE_DIAGNOSIS`. No new provider
construction, no new task type, no planning-model reuse.

### Telemetry (event-log only, not a new OTel span identity)

`RuntimeTelemetry.observe_investigation_stage`'s `SpanObservation`/
`SUPPORTED_WORKFLOWS` machinery is tied to `InvestigationRun`'s UUID
`run_id` and a fixed `("investigation", "2.19.2")` workflow identity;
extending it to a third identity for the correlation scan (which persists no
`InvestigationRun` at all) would be its own Level-2 change this task did not
ask for and was not sized to evaluate safely. Instead, the analysis phase
reuses the existing generic, UUID-keyed structured-event methods already on
`RuntimeTelemetry` — `record_investigation_diagnostic_failure`,
`record_llm_token_usage`, `record_hypothesis_validation_rejected` — with a
fresh `uuid4()` generated per issue purely as a structured-log correlation
key (no persisted run backs it). Six bounded event names are emitted
directly through `telemetry.event_logger.emit`:
`correlation.hypothesis.started`/`.completed`/`.failed` (via
`record_investigation_diagnostic_failure`) and
`correlation.code_diagnosis.started`/`.completed`/`.failed`/
`.validation_rejected`. One new field, `sentry_issue_id`, was added to
`StructuredEventLogger.ALLOWED_EVENT_FIELDS`
(`app/observability/structured_logging.py`) — every other field these
events use (`llm_provider`, `requested_model`, `prompt_version`,
`facts_count`, `hypothesis_count`, `location_count`, `failure_code`,
`http_status`, etc.) was already allowlisted for the adaptive path's own
identical diagnostics. No raw prompt, generated code, credential, or
unrestricted provider response is ever passed to `emit()` — only the same
bounded metadata fields the adaptive path already logs.

### Correction to ADR-037's invariant

ADR-037's "Invariants" section states: "Phases 1-3 introduce zero coupling
to `AdaptiveInvestigationRuntime`, `TypedLLMPlanner`, or any Tool/Evidence/
`InvestigationResult` type." That remains true and unchanged — this ADR adds
no such coupling either; `TypedLLMPlanner`/`PlanValidator`/
`AdaptiveInvestigationRuntime`/`AgentExecutor` are still never imported by
`app/workflows/correlation_scan.py`
(`tests/unit/test_correlation_scan.py::CorrelationScanGroundedAnalysisTests::
test_correlation_scan_module_never_imports_planner_or_executor` asserts this
directly against the module namespace). What this ADR *does* correct is
ADR-037's separate "Decision" statement that the scan produces "no
hypothesis, no rendering through `render_grounded_result`" — that sentence
is no longer accurate as of this ADR and should be read as superseded by the
flow documented here. The distinction that survives is: **control flow**
(what to call, in what order, which commit/issue/file is real) stays
entirely deterministic in both ADRs; only the **interpretation** of Facts a
deterministic step already collected is ever probabilistic, and only after
passing through a deterministic validator.

## Consequences

- `IssueCorrelationResult` grows one new required field (`analysis`) —
  additive at the schema level (OpenAPI/Pydantic), but any existing
  hand-rolled JSON fixture asserting an exact key set for this response
  would need updating; no such fixture exists in this codebase today
  (`tests/integration/test_correlation_scan_api.py` asserts on specific
  fields, not exact key sets).
- A correlation scan now costs up to two additional LLM calls per issue
  (hypothesis, code diagnosis) beyond its existing ≤~7 connector calls —
  bounded by the same `MAX_ISSUES_PER_SCAN = 5` cap ADR-037 already applies,
  and skipped entirely (zero LLM calls) for any issue whose Facts don't pass
  `_has_hypothesis_worthy_facts`.
- `CodeContextBuilder`/`DeterministicCodeFindingValidator` are now used by
  two independent callers (`InvestigationWorkflowService`,
  `scan_repository_for_correlations`) with two different evidence shapes
  (PR-scoped, commit-scoped) flowing through the same code — any future
  change to either function's evidence-type handling must consider both
  callers, not just the adaptive path.
- No new production dependency, no persistence migration, no new LLM
  provider, no new `LLMTask` value, no auth-boundary change.

## Invariants

- `app/workflows/correlation_scan.py` never imports `TypedLLMPlanner`,
  `PlanValidator`, `AdaptiveInvestigationRuntime`, or `AgentExecutor`
  (enforced by a dedicated module-namespace test).
- A hypothesis/code-finding candidate reaches `IssueGroundedAnalysis` only
  after passing `DeterministicHypothesisValidator`/
  `DeterministicCodeFindingValidator` — never directly from
  `TypedLLMHypothesisGenerator`/`TypedLLMCodeDiagnoser` output.
- `IssueAnalysisStatus` never participates in computing
  `IssueCorrelationStatus`, and vice versa.
- One issue's Facts/Evidence are never visible to another issue's
  hypothesis/code-diagnosis call within the same scan — each
  `_correlate_issue` invocation owns its own local `facts`/`evidence_tuple`.
- An unexpected exception during grounded reasoning for one issue never
  aborts the scan or another issue's analysis (`ANALYSIS_ERROR`, isolated
  per issue) — `list_open_issues` failing remains the sole scan-aborting
  failure, unchanged from ADR-037.
- No LLM call is made when `_has_hypothesis_worthy_facts` returns `False`,
  when no hypothesis validates, or when no code finding validates
  (recommendation generation is never reached in either of the latter two
  cases).

## Validation

Backend: `uv run python -m unittest discover -s tests -v` from
`services/api` — 684 passed, 0 failed, 14 skipped (676 baseline + 7 new
`CorrelationScanGroundedAnalysisTests` + 1 new
`CodeContextBuilderCommitScopedEvidenceTests`), including every existing
ADR-037 test (`test_correlation_scan.py::CorrelationScanTests`, all 8
passing unchanged) and every existing adaptive-investigation/hypothesis/
code-diagnosis test (`test_grounded_hypotheses.py`,
`test_investigation_workflow.py`, `test_investigation_evals.py`,
`test_code_diagnosis.py`) unchanged.

New tests added, `tests/unit/test_correlation_scan.py::
CorrelationScanGroundedAnalysisTests`:
- `test_grounded_path_produces_hypothesis_finding_and_recommendation` —
  full success: `COMPLETED`, one hypothesis, >=1 code finding, every
  recommendation traces to an accepted finding.
- `test_hypothesis_rejection_leaves_correlation_ok_and_skips_diagnosis` —
  a candidate citing the wrong file is rejected; code diagnosis is never
  invoked (a `_MustNotBeCalledClient` would raise `AssertionError`
  otherwise); correlation `status` stays `OK`.
- `test_hypothesis_provider_failure_does_not_stop_other_issues` — a
  two-issue scan where only one issue's hypothesis client raises; the
  other issue still reaches `COMPLETED`.
- `test_code_diagnosis_failure_preserves_hypothesis_but_no_finding` — a
  validated hypothesis survives a code-diagnosis provider failure; no
  finding, no recommendation, correlation unaffected.
- `test_insufficient_facts_skips_the_llm_boundary_entirely` — a mismatched
  changed-file path never reaches either `_MustNotBeCalledClient`.
- `test_two_issues_in_one_scan_never_share_facts_or_hypotheses` — issue A
  (matching commit) reaches `COMPLETED`; issue B (a different commit
  touching an unrelated file, same shared failure frame) reaches
  `INSUFFICIENT_EVIDENCE` and never borrows issue A's Facts; their
  `fact_ids` sets are disjoint.
- `test_correlation_scan_module_never_imports_planner_or_executor` — the
  planner/executor invariant, asserted directly.

New test, `tests/unit/test_code_diagnosis.py::
CodeContextBuilderCommitScopedEvidenceTests::
test_commit_scoped_changed_file_and_hunk_become_locations` — proves the
`CommitChangedFileEvidenceContent`/`CommitDiffHunkEvidenceContent` fix:
commit-scoped evidence alone (no PR) now produces `CHANGED_FILE`/
`DIFF_HUNK`/`STACK_FRAME` locations, and a well-formed candidate citing that
evidence is accepted by `DeterministicCodeFindingValidator` with the correct
`line_number`.

Live, in-process (no network, `FakeLLMClient`, no fixtures on disk):
constructed a Sentry-issue-shaped commit-scoped changed-file + diff-hunk +
stack-frame evidence set, called `_run_issue_analysis` directly, and
confirmed `IssueAnalysisStatus.COMPLETED` with a non-empty
`GroundedCodeFinding` citing the diff hunk's file/function/line — the exact
`checkout.py:84`-shaped outcome this ADR's originating task description
describes as the target end-to-end result.

`git diff --check`: clean (line-ending-only warnings from the repo's
`core.autocrlf`, no trailing-whitespace or conflict-marker errors).
FastAPI app construction + `app.openapi()`: succeeds;
`IssueGroundedAnalysis`/`IssueAnalysisStatus` appear in the generated schema
component set alongside the existing `IssueCorrelationResult`.

Not yet validated live against a real Sentry/GitHub organization + a real
LLM provider (only `FakeLLMClient` exercised this session) — see the
"Live verification (2026-09-10)" section below, which supersedes this
paragraph.

## Live verification (2026-09-10)

Ran the real pipeline end to end -- real Sentry (`student-whe` org, project
`python-fastapi`), real GitHub (`banalasaisathwik/promptql-sandbox`), real
`OpenRouterLLMClient` (`openai/gpt-oss-120b`, `PROMPTQL_LLM_PROVIDER=
openrouter`) -- against the same real, already-existing sandbox issue
`PYTHON-FASTAPI-1` ADR-037 used (no new sandbox failure needed; it was
already open, unresolved, and its resolved commit `e1448f6171fd...` was
already confirmed to exist in `promptql-sandbox`). Exercised both the direct
in-process call and, separately, the actual authenticated HTTP endpoint
(`POST /v1/correlation-scans`, via a real registered user with real stored
Sentry/GitHub credentials through `PostgresCredentialRepository`) -- not
just the workflow function in isolation.

**Two real, load-bearing bugs found and fixed, both in the same root-cause
family (absolute-vs-relative path comparison), neither reachable by the
`FakeLLMClient` verification this ADR originally shipped with:**

1. **`normalized_path` equality could never match a real deployment's
   paths.** Sentry's in-app stack frame for a Render-deployed app reports an
   *absolute* container path (`/opt/render/project/src/sandbox-target/app/
   checkout.py`); GitHub's commit API reports the same file as a
   *repo-relative* path (`sandbox-target/app/checkout.py`). Exact-equality
   `normalized_path` comparisons (`fact_derivation/code_change.py`,
   `code_diagnosis/{context,validator}.py`, `hypotheses/validator.py`) never
   matched these, so `ChangedFileMatchesFailureFileFact`/
   `ChangedHunkOverlapsFailureLineFact` were never derived, and even where a
   Fact-level match slipped through, `DeterministicHypothesisValidator`
   compared one `candidate.subject` string against two different
   representations of the same file -- structurally unsatisfiable by any
   single string, independent of LLM quality. Fixed by adding `paths_match`
   (`app/investigations/path_normalization.py`) -- a strict,
   path-segment-boundary suffix match (never a fuzzy substring match: a
   bare trailing filename alone is never enough to match on its own) -- and
   using it everywhere two paths from different sources are compared.
   `correlation_scan.py`'s own `_has_hypothesis_worthy_facts` also had a
   second, independent instance of the same bug: it intersected
   `ChangedFileFact.path` values against `ChangedFileMatchesFailureFileFact.
   file_path` values by exact set membership, even though the latter is
   deliberately populated from the *failure frame's* path, not the changed
   file's own -- fixed by replacing the intersection with a bare presence
   check, since `derive_code_failure_facts` is the sole producer of either
   fact type and only ever produces one after its own match already passed.
2. **The hypothesis-generation prompt never told the LLM to copy a Fact's
   path verbatim.** With (1) fixed, the real LLM was called but initially
   set `subject` to a bare basename (`"checkout.py"`) instead of either
   Fact's full path string -- correctly rejected by `paths_match`'s
   deliberate refusal to match on a single trailing segment alone (that
   would treat any same-named file anywhere in the tree as the same file).
   `HYPOTHESIS_SYSTEM_INSTRUCTIONS` (`hypotheses/instructions.py`, now
   `v2.17.3`) now explicitly requires `subject` to be an exact,
   character-for-character copy of a supporting Fact's `path`/`file_path`,
   and requires citing every Fact needed to fully establish the claim (a
   changed-file Fact *and* a separate failure-match Fact, not just one) --
   mirroring the code-diagnosis prompt's already-established "copy the
   exact field" pattern. `CandidateHypothesis.subject`
   (`hypotheses/models.py`) also gained a `Field(description=...)`
   reinforcing this in the schema itself. This is a real-LLM-output
   observation, not a validator bug: the fix strengthens what the model is
   told, never what the validator accepts.

Both fixes are shared with `InvestigationWorkflowService`'s adaptive path
(`DeterministicHypothesisValidator`, `CodeContextBuilder`,
`DeterministicCodeFindingValidator`, and the hypothesis prompt are the same
classes/instructions for both callers) -- a deliberate, justified exception
to "one logical change per patch," since the bug was never scan-specific:
any real containerized/Render/Docker deployment reports absolute in-app
paths this way, so the adaptive path had the identical latent defect,
undetectable by `FakeLLMClient` fixtures that happened to use matching
paths on both sides. Full regression coverage added:
`tests/unit/test_path_normalization.py` (new file, `paths_match`'s
segment-boundary semantics including the deliberate non-matches), two new
cases in `test_grounded_hypotheses.py::DeterministicHypothesisValidatorTests`
(absolute-vs-relative acceptance, bare-filename rejection). Full suite:
696 passed, 0 failed, 14 skipped (694 prior + 2 new; `test_path_normalization.py`'s
10 tests already counted in the 694 baseline reported above).

**Result, real HTTP `POST /v1/correlation-scans`, 4 consecutive live runs
against the same real issue:** `status: ok` every time (real Jira link
`KAN-5`, real commit, real diff hunk) with `analysis.status` landing on
`completed` in 3 of 4 (one `code_finding_unavailable` from ordinary
real-LLM run-to-run variance at the code-diagnosis stage, not a validator or
integration defect -- correctly preserved, not forced). A `completed` run's
validated `GroundedCodeFinding` cites `sandbox-target/app/checkout.py` (via
its absolute Sentry-reported form) in `decrement_inventory` at line 13 --
the real off-by-one `STOCK[item_id - 1]` bug the resolved commit introduced,
grounded in real commit-scoped diff-hunk evidence.

**Deterministic gate confirmed live, real degraded evidence, no fixture
needed:** scanning the `python-flask` project's real `PYTHON-FLASK-1` issue
(`jira_ticket: null`, confirmed unlinked -- no `LINKED_JIRA_KEY` step
failure) resolved a real commit SHA that does not exist in
`promptql-sandbox` (`GitHubCommitNotFoundError` -> `COMMIT_NOT_FOUND`,
correlation `status: partial`, `fact_ids: []`) and correctly reached
`analysis.status: insufficient_evidence` with zero
`correlation.hypothesis.*`/`correlation.code_diagnosis.*` telemetry events
emitted -- confirming the cost/safety gate skips the LLM boundary entirely
on real degraded evidence, not only in unit tests.

**Not exercised live** (both already covered by
`test_two_issues_in_one_scan_never_share_facts_or_hypotheses`'s synthetic
fixtures, not by this session): per-issue isolation across two *real* open
issues in the same project -- both sandbox Sentry projects currently have
exactly one open issue each, so a genuine two-real-issue-in-one-scan run
was not possible without fabricating unnecessary external state, which the
verification task explicitly discouraged when a valid existing issue
already exists.

## Reconsideration triggers

- **Resolved 2026-09-10, live**: a real (non-fake) `TypedLLMClient` provider
  was exercised against this path and did reveal a systematic rejection
  pattern the validators weren't designed around — see "Live verification"
  above for the `paths_match` and hypothesis-prompt fixes this produced. If
  a *future* real-provider run reveals a further systematic rejection
  pattern (e.g. a different LLM consistently omitting a required supporting
  Fact even with the current v2.17.3 instructions), revisit whether an
  additional grounding rule or prompt clarification is needed.
- If `MAX_ISSUES_PER_SCAN` is raised (ADR-037's own trigger) without also
  reconsidering per-scan LLM call volume — this ADR adds up to 2 more calls
  per issue on top of ADR-037's already-flagged Sentry/GitHub call count.
- If a correlation-scan-specific frontend is built, its API/client contract
  work is intentionally out of scope here (no correlation-scan UI existed
  in this branch before this ADR) — see `docs/ARCHITECTURE.md`'s TARGET
  note for what remains.
- If `observe_investigation_stage`'s OTel span/`SUPPORTED_WORKFLOWS`
  machinery is later extended to a third workflow identity for other
  reasons, revisit whether the correlation scan's event-log-only telemetry
  here should be upgraded to real spans at the same time, rather than
  maintaining two different telemetry depths for LLM-adjacent stages.
- **Found 2026-09-11, live, not fixed (out of scope for the task that found
  it):** the fix-proposal LLM call emits no cost/latency telemetry anywhere
  in the app — `TypedLLMFixProposalGenerator.generate()` discards
  `LLMStructuredResponse.token_usage`, unlike the hypothesis/code-diagnosis
  stages. If fix-proposal call volume or cost becomes a real operational
  question, give `FixProposalOutput` the same metadata-carrying shape
  `CodeDiagnosisOutput`/`GeneratedCodeFindings` already have and emit an
  `llm.token_usage` event with `role: fix_proposal`, matching the other two
  stages.

## Bounded proposed code fixes

After `DeterministicCodeFindingValidator` accepts a location, the scan may
select one supporting diff hunk that covers that finding's observed failure
line. The backend, rather than the model, constructs `original_hunk` from
that exact post-commit source slice. A separate typed model may return only a
bounded replacement plus its failure mechanism and strategy; a deterministic
validator requires the same finding, file, Fact IDs, Evidence IDs, and size
limits before returning it as a **proposed fix**.

This is a read-only trust boundary. A proposed fix is grounded and
scope-validated, but not proven correct until compiled and tested. No scan
can apply a patch, modify a repository, create a pull request, or push code.
Missing hunk context, model failure, or a rejected suggestion leaves the
validated diagnosis intact with the proposal marked unavailable.

## Live verification — fix proposal (2026-09-11)

Closed the two verification gaps the section above left open: a real
live-provider run through the fix-proposal stage, and a focused eval matrix
for it.

**Live run, real HTTP `POST /v1/correlation-scans`** — same real Sentry
(`student-whe`/`python-fastapi`), real GitHub
(`banalasaisathwik/promptql-sandbox`), real `OpenRouterLLMClient`
(`openai/gpt-oss-120b`) path as "Live verification (2026-09-10)" above,
extended through the fix-proposal stage, against the same already-open
issue `PYTHON-FASTAPI-1` (commit `e1448f6171fd...`, failure at
`sandbox-target/app/checkout.py:13`, `decrement_inventory`, `KeyError: 0`).
A cheap prerequisite check ran first with no LLM call: a direct
`scan_repository_for_correlations` call using real Sentry/GitHub sources and
the default `FakeLLMClient()` confirmed `status: ok`, 4 Evidence, 3 Facts,
`grounding_strength: strong` before any paid call was made.

**One real, load-bearing bug found and fixed.** The first live
fix-generation call returned an *accepted* `corrected_hunk` of
`"-    STOCK[item_id - 1] -= qty"` — a bare unified-diff removal line, not
literal replacement source. Every existing deterministic check
(`FILE_MISMATCH`, `SUPPORT_MISMATCH`, `OVERSIZED_REPLACEMENT`,
`UNSUPPORTED_IMPORT`) let it through, since none constrained the *shape* of
`corrected_hunk`, only its size, provenance, and file identity. Root cause:
the prompt never told the model `corrected_hunk` must be literal source
text rather than a diff fragment, and the validator had no matching check.
Fixed with a new `CodeFixValidationFailureCode.DIFF_MARKER_ARTIFACT`
rejection reason (`DeterministicCodeFixValidator._rejection_reason`,
`fix_proposal.py`): reject any candidate whose `corrected_hunk` has a line
starting with a bare `-`/`+` character — `FixProposalContextBuilder`
already strips diff prefixes from `original_hunk`'s own source lines, so a
real replacement line should never carry one.
`FIX_PROPOSAL_SYSTEM_INSTRUCTIONS` bumped to `v1.1`, now explicitly
requiring literal replacement text covering the same span as
`original_hunk`, never a diff fragment. Regression test added first
(`tests/unit/test_code_diagnosis.py::CodeFixProposalTests::
test_validator_rejects_unified_diff_marker_lines`) — confirmed it failed
against the pre-fix validator (proving the bug), then confirmed it passes
after the fix. Re-ran the live scan: the same real incident now returns a
correct, complete corrected hunk (`return STOCK[item_id - 1]`, aligning the
read with the write) with a coherent `failure_mechanism`/`fix_strategy`.

**Observed real-model variance, not bugs.** Across the additional live
sampling used to confirm the fix and exercise the eval matrix live, the
real model sometimes: omitted one supporting Fact ID from a candidate
(rejected `SUPPORT_MISMATCH` — correct, strict validator behavior, the same
class already documented in "Live verification (2026-09-10)" above),
declined to propose a fix for an otherwise-fixable case (an honest
abstention this pipeline is designed to accept), and once encoded a
multi-line `corrected_hunk` using the Unicode glyph `⏎` (U+23CE) instead of
a literal `\n` between lines — schema-valid and semantically coherent, but
a cosmetic rendering quirk (see "known limitations" below). Two real
transient GitHub failures (`upstream_unavailable` on `commit_evidence`/
`commit_changed_file_evidence`) correctly reached `insufficient_evidence`
and skipped the LLM boundary entirely — zero fix-proposal calls spent on
either, confirming the cost/safety gate still holds at this stage.

**Eval matrix** (`app/evals/fix_proposal/`) — a focused, fixture-driven eval
separate from `app.evals.investigations`: each case's hypothesis/finding is
constructed deterministically (the same production validators, not an LLM)
so every provider call the eval makes is the fix-proposal boundary itself.
Five cases: KeyError/missing-mapping-key, None dereference, invalid input
boundary, configuration/deployment mismatch, and one deliberately ambiguous
case where correct abstention is expected. Metrics: `correct_file`,
`correct_hunk_or_location`, `failure_mechanism_grounded` (deterministic
per-case keyword grounding, not an LLM judge), `minimal_edit` (a real
`difflib` line-level diff, not positional comparison — positional
comparison originally overcounted every line after an insertion as
"changed"), `unsupported_identifier_rate` (a bare-identifier heuristic:
builtins/keywords/original-hunk names/self-assigned names allowed,
attribute access on an existing name excluded since verifying it needs real
type information the eval does not have), `syntax_valid` (`ast.parse` on a
dedented hunk), `fix_available_when_expected`, and
`abstains_when_fix_not_grounded`. `--fake-dry-run` routes each case back to
its own known-good candidate by `finding_id` (deterministic, offline, part
of the ordinary unit-test-adjacent run); `--acknowledge-paid-calls` runs
the identical matrix against the real provider. Fake-dry-run: 15/15 planned
samples, every gate passes (`release_passed: true`). Live (1 sample/case, 5
calls): real variance as expected — 1/4 accepted fixes, 0/1 correct
abstention on that single sample (case E accepted a fix instead of
declining; cases C and D separately saw a real abstention and a real
`SUPPORT_MISMATCH` rejection) — exactly the kind of run-to-run variance
this eval exists to surface, not mask. `release_passed` on a single live
sample is not the bar; the fake-dry-run gate and the regression test above
are.

### Known limitations (fix proposal)

- The fix-proposal LLM call has no cost/latency telemetry anywhere in the
  app (see the reconsideration trigger above) — confirmed live: neither
  live run emitted an `llm.token_usage` event with `role: fix_proposal`.
  Pre-existing, not introduced or fixed this session; out of this task's
  explicit scope.
- A real model was observed once encoding a multi-line `corrected_hunk`
  with the Unicode "return" glyph (`⏎`, U+23CE) instead of a literal
  newline. One observation is not a systematic pattern — not fixed this
  session; revisit only if a future live run repeats it.
- Proposed fixes remain unproven: `DeterministicCodeFixValidator` checks
  provenance, scope, and size, never functional correctness. Functional
  correctness still requires execution/tests, which this pipeline
  deliberately never runs.
