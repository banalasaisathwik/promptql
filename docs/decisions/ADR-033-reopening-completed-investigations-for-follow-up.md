# ADR-033: Reopening completed investigations for follow-up questions

- Status: Accepted
- Date: 2026-08-28
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

`InvestigationRun` (`app/runtime/investigation_models.py`) and
`MergeReadinessRun` (`app/runtime/models.py`) both use the same `RunStatus`
enum and are both written through `PostgresRunRepository`
(`app/database/postgres_run_repository.py`). That repository already treats
the two run types differently in three places — `_run_values`,
`_save_steps`, `_validate_run_identity` — each guarded by
`isinstance(run, InvestigationRun)`. Everywhere else, both run types share
one persistence path, including the transition check in
`_update_existing_run`, which enforces `ALLOWED_RUN_TRANSITIONS[stored_status]`
(`app/runtime/state.py`) regardless of run type. `ALLOWED_RUN_TRANSITIONS`
maps `RunStatus.COMPLETED`, `FAILED`, and `CANCELLED` to empty sets, so no
run of either type can currently leave a terminal state.

The product needs a user, after an investigation completes, to ask a
follow-up question against the same case and get a new answer that builds
on everything already gathered — without re-running discovery from
scratch and without losing the original answer. That requires an
`InvestigationRun` to move from `COMPLETED` back to `RUNNING`, which
`ALLOWED_RUN_TRANSITIONS` does not permit today. A prior read-only
diagnostic examined what would be required to allow this and confirmed
several second-order consequences: a naive re-run resets the tool-call
budget, resets round numbering, double-counts fact-recurrence, and
overwrites the original result if the completion path is invoked
unchanged. This ADR consolidates the resolved decisions on scope, budget,
round numbering, fact-recurrence counting, result storage, follow-up
volume, and evidence rehydration; it does not implement any of them.

## Decision drivers

- The terminal-state guarantee for `MergeReadinessRun` protects a
  merge/no-merge policy decision that may already have been acted on
  (surfaced to a human, or gating CI); it must not become reopenable as a
  side effect of solving a problem that is specific to investigations.
- `ALLOWED_RUN_TRANSITIONS` and `RunStatus` are shared, general-purpose
  runtime state machinery; loosening them widens behavior for every current
  and future consumer, not just investigations.
- A budget that can be reset by asking a follow-up question is not a
  bound on anything — it must accumulate across the whole case, and it
  must never grow beyond what the case was originally granted.
- Round numbers are referenced in telemetry, planner history, and action
  summaries; silently restarting at round 1 for a follow-up would make
  round numbers ambiguous within one case.
- The fact-recurrence counter (ADR-031) measures how many independent
  investigations reproduced a fact type against a repository; counting
  follow-up rounds of the same investigation as separate occurrences would
  corrupt that meaning.
- The product requirement is a growing thread (original answer stays
  visible, the follow-up answer appends below it), not an edited answer —
  overwriting the original result is not an acceptable implementation of
  "ask a follow-up."
- The public demo deployment (`docs/ARCHITECTURE.md`, "Public demo
  deployment") already treats `POST /v1/investigations` as an
  abuse-relevant endpoint worth rate-limiting; an unbounded reopen path
  would be a second, unguarded way to drive repeated work against the same
  case.
- Reuse the established `isinstance`-based special-casing pattern already
  present in the repository layer rather than inventing a new mechanism.

## Options considered

### Option A: Loosen `ALLOWED_RUN_TRANSITIONS` globally

Add `RunStatus.RUNNING` to `ALLOWED_RUN_TRANSITIONS[RunStatus.COMPLETED]`
directly. This is the smallest textual change, but the map is shared by
both run types, so it would also let a completed `MergeReadinessRun`
transition back to `RUNNING`. That weakens the terminal guarantee for an
unrelated workflow whose completed decisions are meant to be immutable.
Rejected as genuinely dangerous per the diagnostic.

### Option B: Scoped `isinstance(run, InvestigationRun)` exception in the repository layer (chosen)

Add a fourth `isinstance(run, InvestigationRun)` branch in
`PostgresRunRepository._update_existing_run`, alongside the three that
already exist, that permits `COMPLETED -> RUNNING` specifically when the
incoming run is an `InvestigationRun`. `ALLOWED_RUN_TRANSITIONS` and
`RunStatus` are not edited at all; a `MergeReadinessRun` with
`stored_status == "completed"` still falls through to the untouched shared
check and is still rejected, exactly as today. This follows the repository
layer's existing pattern for type-specific behavior instead of introducing
a new one.

### Option C: Model a follow-up as a new linked `InvestigationRun`

Instead of transitioning the same run, create a second `InvestigationRun`
row referencing the original via a `parent_run_id`, leaving transition
logic untouched entirely. This avoids the transition question, but it
fragments the tool-call budget, round numbering, and fact-recurrence
counting across two rows, requiring a new cross-run aggregation layer for
all three just to reconstruct what should be one case's bookkeeping. It
also produces two independently `COMPLETED` rows for what the product
treats as one growing thread, which does not match the display
requirement any more directly than Option B does. Rejected: it trades one
well-scoped repository-layer change for three new consolidation problems.

## Repository owner reasoning

The owner selected Option B specifically because it keeps the blast radius
of the change at the repository layer's existing type-dispatch point and
leaves the shared state machine byte-for-byte unchanged. The owner further
specified, as resolved decisions rather than open questions for this ADR:
the budget must accumulate across the case but never exceed its original
cap; round numbering must continue rather than restart; fact-recurrence
must count the case once per fact type, not once per round; the original
result must remain independently visible alongside the follow-up result,
which requires changing `InvestigationRun.result` from a single nullable
field to an ordered sequence; and follow-up volume per case must be either
explicitly bounded or explicitly, deliberately deferred with a named
reconsideration trigger — not left silently unbounded.

## Reasoning review

Option B correctly isolates the risk: nothing about `MergeReadinessRun`'s
codepath changes, because the shared map and enum are untouched and the
new branch only fires for `InvestigationRun`. The budget-accumulation and
round-continuation requirements are both correctly derived from choosing
"same run, reopened" over "new linked run" — they are the direct cost of
keeping one row per case. The fact-recurrence requirement surfaces a real
implementation risk worth flagging explicitly: `_record_fact_recurrence`
(`app/workflows/investigation.py:595`) today calls
`record_occurrence` unconditionally for every distinct `fact_type` in the
run's current `FactSet` every time it runs, with no per-`run_id`
deduplication in `FactRecurrenceRepository.record_occurrence` itself
(`app/runtime/repository.py`, `app/database/postgres_fact_recurrence_repository.py`).
If the completion path is invoked unchanged on a follow-up round, it will
call `record_occurrence` again for fact types already counted in the
first round's completion, double-counting them. Satisfying "at most once
per `(run_id, fact_type)`" requires the completion path to compute a
delta — fact types newly observed since the last time this `run_id`
recorded them — not just call it with the full current `FactSet`, as it
does today. This is not automatic and must be built. Fixing the budget cap
at the original grant, rather than letting it grow, is also the only
reading of "budget" consistent with the stated driver — a cap that a user
can raise by asking another question is not a cap.

## Decision

Scope this change to `InvestigationRun` only, using the same
`isinstance(run, InvestigationRun)` special-casing already used in
`PostgresRunRepository._run_values`, `_save_steps`, and
`_validate_run_identity`. `ALLOWED_RUN_TRANSITIONS` and the shared
`RunStatus` enum are not modified in any way; `MergeReadinessRun`'s
transition behavior, including its `COMPLETED`/`FAILED`/`CANCELLED`
terminal guarantee, is unaffected by this ADR. Only a `COMPLETED`
`InvestigationRun` may reopen to `RUNNING`; `FAILED` and `CANCELLED`
investigations are not addressed by this ADR and remain non-reopenable.

**Budget.** `ExecutionBudget.max_tool_calls` is fixed at the value granted
to the case at original creation. Follow-ups draw down remaining budget;
they never add to the cap, and no mechanism in this ADR increases it. A
follow-up round starts `AdaptiveInvestigationRuntime.investigate()` with
`remaining_tool_calls` computed as the original cap minus everything
already consumed across every prior round of this `run_id` — never a
fresh full budget. A follow-up asked against a case that has already
exhausted its budget is still permitted to run: it can only reason from
evidence already gathered, with zero new tool calls available, since
`investigate()` already short-circuits to a terminal state when
`remaining == 0` before any planner call for that round.

**Round numbering.** Round numbers continue across follow-ups: if the
original investigation ended at round 3, a follow-up's first new round is
round 4. `AdaptiveInvestigationRuntime.investigate()` gains a round-offset
parameter (`initial_rounds`, or equivalent) it does not have today, so the
`for round_number in range(1, MAX_PLANNING_ROUNDS + 1)` loop in
`replanning.py` starts from `initial_rounds + 1` on a follow-up instead of
always starting at 1.

**Fact-recurrence counting.** The completion path must increment the
repository-scoped fact-recurrence counter (ADR-031) at most once per
`(run_id, fact_type)` for the life of the case, regardless of how many
follow-up rounds that `run_id` goes through. This requires the caller of
`record_occurrence` to compute the delta of fact types newly observed
since the last recorded set for this `run_id`, not resubmit the full
current `FactSet` on every completion. The counter continues to measure
"how many separate investigations produced this fact type," not "how many
rounds" — recording the same case's fact types again on every follow-up
would conflate the two.

**Follow-up cap.** A case may be reopened at most 3 times
(`MAX_FOLLOW_UPS_PER_CASE = 3`, mirroring the existing
`MAX_PLANNING_ROUNDS = 3` precedent for how many bounded units of
activity one investigation workflow already allows). A fourth reopen
attempt is rejected deterministically, the same way an out-of-range
transition is rejected today, rather than left to whatever the tool-call
budget happens to still allow. This is chosen over leaving the count
unbounded because, per the budget invariant above, a budget-exhausted
follow-up is still a cheap-but-nonzero request (LLM-free planning, but
still a render pass, a persistence write, and an HTTP round trip) and the
public demo deployment has no other control on repeated requests against
one existing case.

**Result semantics.** A follow-up produces a new `GroundedInvestigationResult`
via a fresh call to `render_grounded_result()` over the full cumulative
evidence and fact set at that point. Since `render_grounded_result` is
already a pure function of facts/hypotheses/evidence with no run-scoped
side effects, and facts are already re-derived deterministically from
evidence, no new merge logic is needed to produce a follow-up's answer.
What changes is storage: `InvestigationRun.result: GroundedInvestigationResult | None`
becomes an ordered, append-only sequence — one entry per completed
turn/round-boundary — so the original result remains independently
retrievable and displayed, not overwritten. This is a domain schema change
(`app/runtime/investigation_models.py`) with a corresponding persistence
change to how the `result` column is populated in
`PostgresRunRepository._run_values`/`_stored_run_values`, matching the
product requirement of a growing thread rather than an in-place update.

**EvidenceStore rehydration.** Confirmed lossless. `WorkingMemory.evidence_content`
(`app/runtime/investigation_models.py`) stores complete `Evidence` objects,
not references, and is persisted in full as part of `investigation_state`
(`_json_value(run.state)` in `postgres_run_repository.py`). Reopening
rebuilds an `EvidenceStore` by calling `store.put()` for each item in
`state.working_memory.evidence_content`, in persisted order, before the
follow-up round executes. `EvidenceStore.put()` is already idempotent per
`evidence_id`, so replaying the full persisted sequence reconstructs a
store equivalent in content to the one present at original completion
time.

## Consequences

- The repository layer gains one new `isinstance(run, InvestigationRun)`
  branch permitting `COMPLETED -> RUNNING`; no other run-type or
  status-pair behavior changes anywhere in `postgres_run_repository.py`.
- `InvestigationRun.result` becomes `InvestigationRun.results` (or
  equivalent), an ordered tuple, with a new lifecycle invariant: a
  `COMPLETED` investigation has at least one result, and the sequence is
  append-only — no entry is ever removed or replaced.
- This is a wire-format change, not just a backend-internal one:
  `InvestigationResponse` (`app/api/v1/models.py:73`) subclasses
  `InvestigationRun` directly and inherits the field as-is, so the HTTP
  response shape changes. On the frontend, this requires corresponding
  updates to `apps/web/src/features/inspection/types.ts` (the
  `InvestigationRun`/`InvestigationResponse` type currently declares
  `result: GroundedInvestigationResult | null` at a single field, e.g.
  `types.ts:494`), `responseValidation.ts` (whose runtime narrowing logic
  currently validates `value.result` as one nullable value in several
  places, e.g. around `responseValidation.ts:859-888`, and will need to
  validate an ordered sequence instead), and `InvestigationDashboard.tsx`
  (`const result = run.result` at `InvestigationDashboard.tsx:69`, which
  reads the single field directly and will need to render a sequence).
  `InvestigationTraceView.tsx` does not currently reference `result` at
  all, but consumes the same response shape and should be reviewed to
  confirm it makes no implicit single-result assumption before this ships.
  This is the same class of frontend-contract change the Day 1
  `EvidenceStore` refactor required — flagged explicitly here, before
  implementation, rather than discovered afterward.
- `AdaptiveInvestigationRuntime.investigate()` gains a round-offset
  parameter it does not have today; `MAX_PLANNING_ROUNDS` continues to
  bound rounds *per case*, not per follow-up call, once the offset is
  wired through.
- The fact-recurrence write path (`_record_fact_recurrence` in
  `app/workflows/investigation.py`) must be changed from "record every
  fact type in the current `FactSet`" to "record only fact types not
  already recorded for this `run_id`" — a real code change, not a
  no-op consequence of the schema change alone.
- A new `MAX_FOLLOW_UPS_PER_CASE` bound is introduced and must be checked
  deterministically before a reopen is accepted, alongside the existing
  transition check.
- A database migration is required to widen persisted result storage from
  a single JSON object to an ordered array; exact migration mechanics are
  implementation-planning work, not resolved by this ADR.
- `MergeReadinessRun` transitions, `ALLOWED_RUN_TRANSITIONS`, `RunStatus`,
  and cancellation's `CANCELLED`-as-terminal guarantee are unaffected —
  not materially relevant to this ADR's risk surface by construction of
  Option B.

## Invariants

- `ALLOWED_RUN_TRANSITIONS` and `RunStatus` remain exactly as defined in
  `app/runtime/state.py` and `app/runtime/models.py`; this ADR adds no
  entries to either.
- Only `InvestigationRun` may transition `COMPLETED -> RUNNING`, and only
  through the new scoped repository-layer branch; `MergeReadinessRun`
  reaching `COMPLETED`, `FAILED`, or `CANCELLED` remains a true dead end.
- The total tool-call budget for a case is fixed at the original
  `ExecutionBudget.max_tool_calls`; follow-ups draw down remaining budget
  and never add to the cap. A follow-up on a case that has already
  exhausted its budget can only reason from existing evidence, with zero
  new tool calls available.
- A case may be reopened at most `MAX_FOLLOW_UPS_PER_CASE` (3) times; a
  further reopen attempt is rejected deterministically.
- `round_number` is strictly increasing across the life of one `run_id`;
  no follow-up restarts numbering at 1.
- The fact-recurrence counter increments at most once per
  `(run_id, fact_type)` for the life of a case, independent of how many
  follow-up rounds occur.
- `InvestigationRun.results` is ordered and append-only; the first element
  is always the original result and is never removed or replaced by a
  follow-up.
- Reopening replays `store.put()` for every item in the persisted
  `working_memory.evidence_content`, in persisted order, before any new
  round executes.

## Validation

Not yet implemented; this ADR precedes implementation. When implemented,
the following existing tests were flagged by the prior diagnostic as
needing genuine reconsideration — not a mechanical rename or signature
update — because they assert the merge-readiness-only terminal guarantee
this ADR must not weaken:

- `test_completed_and_failed_runs_cannot_return_to_running`
  (`tests/unit/test_runtime_state.py:57`)
- `test_terminal_run_rejects_a_new_pending_snapshot`
  (`tests/integration/test_postgres_runtime_persistence.py:158`)
- The 16 occurrences across `test_runtime_state.py`'s transition-map suite
  that assert terminal-state behavior against `ALLOWED_RUN_TRANSITIONS`
  and `RunStatus`.

Each must be re-examined during implementation to confirm it still
expresses a merge-readiness-only guarantee after this change — for
example, a test that currently asserts "a completed run cannot return to
running" using a `MergeReadinessRun` fixture must keep failing exactly as
before; if any such test would need to change to keep passing, that is a
signal the scoping was not actually preserved, not a signal to update the
test. None of these should silently continue passing by accident once the
new `InvestigationRun`-only branch exists — each needs an explicit
pass/fail check against the post-change code, not just a read of the diff.

New coverage required at implementation time (not yet written): a
follow-up round that reuses budget correctly (not reset), a follow-up on
an already-exhausted-budget case that still completes with zero new tool
calls, a fourth reopen attempt on one case being rejected, a follow-up
round numbered as a continuation, a fact type recorded on the original
round not re-recorded on a follow-up producing the same fact type, both
results retrievable and ordered after a follow-up, evidence rehydration
producing a store with identical content to the one at original
completion, and the frontend contract change (`types.ts`,
`responseValidation.ts`, `InvestigationDashboard.tsx`) validated against
an updated fixture response shape.

## Follow-up amendment: prior-turn context on the planner boundary

Implementation surfaced one question this ADR left unresolved: when a
follow-up's question becomes the `investigation_goal` for its new round(s)
(as decided above, under "Round numbering" and "Result semantics"), the
original question and its answer are not part of that goal string and are
not part of `facts`/`evidence` either, since those are re-derived
deterministically from evidence and carry no narrative. Without a
deliberate carrier, the planner would silently lose the context of what
was already asked and concluded, and a naive fix -- concatenating the
prior question and answer into the new `investigation_goal` string --
would conflate this run's actual instruction with earlier narrative the
planner might mistake for current-run evidence.

`RememberedRepositoryPattern`/`remembered_patterns` (`app/investigations/
planning/models.py`) already solves the identical shape of problem for a
different source of prior context: repository-scoped Fact-recurrence
history is surfaced to the planner as its own labeled `PlannerInput`
field, with its own guardrail section in the system instructions
(`PLANNER_REMEMBERED_PATTERNS_SECTION`, `app/investigations/planning/
instructions.py`) explicitly marking it as history, not evidence, not a
hypothesis, and not this run's conclusion. This ADR adopts the same
pattern for prior-turn context: `PlannerInput` gains a new field,
`prior_result_summary: str | None = None`, populated only on a follow-up
round with the previous turn's `GroundedInvestigationResult.summary`.
`ContextBuilder.build()` (`app/investigations/planning/prompt.py`) accepts
it as an explicit keyword argument, mirroring exactly how it already
threads `fact_recurrence_repository` through to populate
`remembered_patterns`. A parallel guardrail section is appended to the
planner's system instructions only when `prior_result_summary` is
present, telling the planner this is the prior turn's answer, not new
evidence and not already-established fact, so it cannot be cited as
grounding for the new round's plan.

This keeps the same invariant the original ADR already states for
`remembered_patterns`: untrusted narrative content crosses the planner
boundary only through an explicitly labeled channel the planner is told
how to treat, never folded into the fields that carry this run's actual
evidence and facts.

## Reconsideration triggers

Revisit if a product requirement emerges to reopen `FAILED` or
`CANCELLED` investigations — this ADR deliberately does not address
either. Revisit the repository-layer scoping mechanism if a third run type
is ever introduced that also needs reopening, since a third
`isinstance` branch per call site may indicate the dispatch pattern itself
should be revisited rather than repeated again. Revisit fact-recurrence
delta-tracking if `FactRecurrenceRepository` itself later gains
per-`run_id` idempotency, which could simplify or remove the caller-side
delta computation this ADR requires. Revisit `MAX_FOLLOW_UPS_PER_CASE`
specifically if the Phase 5 public-demo deployment's rate-limiting
(`PerIpRateLimitMiddleware`, `docs/ARCHITECTURE.md` "Public demo
deployment") turns out insufficient against reopen-endpoint abuse in
practice — that interaction, not a guess about usage patterns, is the
intended trigger for tightening or loosening this cap.
