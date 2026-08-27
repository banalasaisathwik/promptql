# ADR-031: Repository-scoped Fact-type recurrence memory

- Status: Accepted
- Date: 2026-08-27
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

Every current `InvestigationFact` (`app/investigations/models.py`) subclasses
`_EvidenceBackedFact`, which requires a non-empty `evidence_reference_ids` and
is validated so that `fact.evidence_reference_ids` is always a subset of the
current run's evidence IDs (`InvestigationResult` validation). A prior read-only
diagnostic confirmed nothing today reads or writes state keyed only by
`(repository_owner, repository_name)` independent of a single run: every
occurrence of that pair lives inside `InvestigationRequest` or an evidence
content type, both scoped to one request. `workflow_runs.investigation_state`
is JSONB but keyed by `run_id`, not by repository.

Distinct investigations against the same repository can still recognize the
same *kind* of Fact recurring (for example, `deployment_preceded_incident`
appearing across several unrelated incidents for the same repository) without
any single Fact instance ever repeating: every Fact's `fact_id` and
`evidence_reference_ids` are unique per run by construction, so instance-level
matching across runs would never fire. Repository-scoped memory needs to
count at the level of the Fact's `fact_type` discriminator, not the Fact
instance.

## Decision drivers

- Preserve the existing evidence-reference invariant on `_EvidenceBackedFact`;
  do not weaken or bypass it to let old evidence "count" in a new run.
- Keep the write trigger deterministic; do not introduce an LLM judgment call
  for what counts as durable without its own sign-off, consistent with how
  every other LLM/deterministic boundary in this project has been decided.
- Avoid guessing at a richer memory shape (naming aliases, narrative
  root-cause patterns) before a concrete read consumer needs it.
- Reuse the established migration/session-factory/repository patterns already
  used for `workflow_runs`/`workflow_steps` rather than inventing a new
  persistence style.

## Options considered

### Option A: Track exact Fact-instance recurrence

Store each Fact instance and look for byte-identical repeats across runs. This
never fires: every Fact's `evidence_reference_ids` differ per run because
evidence is per-run by construction, so this option cannot express recurrence
at all and was rejected outright.

### Option B: Track Fact-type recurrence per repository (chosen)

Count how many distinct investigation runs for a given
`(repository_owner, repository_name)` produced at least one Fact of a given
`fact_type`. This is expressible today with the existing discriminator field
on every `InvestigationFact` subclass, requires no new Fact subclass, and
needs no LLM involvement — it is pure deterministic bookkeeping over already-
validated domain state.

### Option C: LLM-proposed candidate memory with deterministic acceptance gate

Let a model propose richer memory candidates (naming aliases, narrative
root-cause categories) validated by a deterministic acceptance gate before
persisting, mirroring the `CandidateHypothesis` -> deterministic validator
pattern (ADR-024). This is the more valuable shape long-term but is a new
deterministic/LLM boundary and a new persisted authority — a Level 2
architectural decision under this project's decision rubric. It is
deliberately deferred, not scoped into this ADR.

## Decision

Add a `repository_fact_recurrence` table keyed by the composite
`(repository_owner, repository_name, fact_type)`. At investigation completion,
for each distinct `fact_type` present in the final `FactSet` (deduplicated
within the run, since one run can produce several Facts of the same type),
deterministically upsert the counter row: increment `occurrence_count`, and
update `last_observed_run_id`/`last_observed_at`. When `occurrence_count`
first reaches a fixed threshold, set `promoted_at` once; it is never cleared.

The threshold is `3`. One occurrence could be incidental to a single
incident; two could still plausibly be the same root cause investigated
twice in adjacent rounds of the same underlying problem. A third *independent*
run reproducing the same Fact type against the same repository is the first
point where "this keeps happening here" stops being a coincidence about one
incident and becomes a property of the repository worth surfacing — the same
intuition behind "three strikes" thresholds used elsewhere for distinguishing
noise from a pattern, without requiring a statistical model this project has
no calibrated data to fit.

The new row is **not** a Fact subclass. It cannot satisfy
`_EvidenceBackedFact`'s evidence-reference invariant across runs — a prior
run's evidence IDs are not members of the current run's evidence set — and
representing accumulated cross-run counts as if they were current-run
evidence-backed conclusions would misrepresent their provenance. It is a
separate, explicitly-labeled domain concept engineered for the write side only;
this ADR does not implement a read/injection path into planner or hypothesis
prompts.

## Consequences

- A new table, SQLAlchemy model, and a small deterministic repository
  protocol/implementation pair are added, following the same session-factory
  and migration conventions as `workflow_runs`/`workflow_steps`.
- No Fact subclass, evidence-reference invariant, or existing Fact-derivation
  rule changes.
- The counter write is a side effect of investigation completion, not part of
  `GroundedInvestigationResult`; a persistence failure there is reported
  through existing diagnostic telemetry and does not fail an otherwise
  successful investigation run.
- This ADR intentionally does not add a `PlannerInput` field or any prompt
  injection — that is a read-consumer decision for a later change once the
  write path has real data to read.
- The richer LLM-proposed-candidate memory (Option C) remains unimplemented.
  Building it without this ADR's boundary would risk letting an unvalidated
  model claim become durable, persisted "knowledge" about a repository.

## Invariants

- `repository_fact_recurrence` is keyed by
  `(repository_owner, repository_name, fact_type)`; `fact_type` is restricted
  to the discriminator values defined on `InvestigationFact`.
- `occurrence_count` only increases; `promoted_at`, once set, is never cleared
  or moved earlier.
- A single run contributes at most one increment per distinct `fact_type`,
  regardless of how many Fact instances of that type it produced.
- The write path never reads or reconstructs another run's Evidence or Facts;
  it only reads the completing run's own final `FactSet` and its own
  `InvestigationRequest` identity.

## Validation

Unit tests cover: two occurrences of a `fact_type` for one repository do not
promote; the third occurrence promotes; a different repository's counter is
unaffected by another repository's occurrences; a `fact_type` that never
recurs stays at `occurrence_count == 1` indefinitely. These run against the
in-memory fake repository and, for the real upsert, against the opt-in
guarded PostgreSQL test path. All exercised through the real
`InvestigationWorkflowService` completion path with the fake LLM/planner
clients already used elsewhere in this suite — no live provider calls.

## Reconsideration triggers

Revisit this ADR once a concrete consumer wants to read `promoted_at`
knowledge back into planning or hypothesis generation — that read path, and
whether promoted counters should ever be demoted or expire, deserves its own
decision once there is a real prompt-injection design to evaluate. Revisit the
threshold value if measured production recurrence patterns show `3` fires too
eagerly or too rarely. Revisit Option C (LLM-proposed richer memory) only as
its own ADR, with its own deterministic acceptance gate, once type-recurrence
memory alone proves insufficient for a real use case.
