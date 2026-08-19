# Execution plan: V2.17-V2.18 grounded hypotheses

- Status: Completed
- Related milestones: V2.17, V2.18
- Related ADR: ADR-024

## Objective

Generate a maximum of three structured, untrusted causal candidates from the
completed V2.16 Fact state, then accept only candidates whose selected Facts
satisfy deterministic generic relationship rules.

## Current behavior

V2.16 stops after bounded planning/execution and deterministic fact derivation.
It has a provider-neutral `TypedLLMClient`, but no hypothesis generation or
semantic grounding. The current Fact union supports a code-change relationship;
it does not yet establish generic dependency-failure relationships.

## Implemented scope

- A fact-first `HypothesisGenerationInput`, versioned prompt, and injected
  provider-neutral generator return only bounded `CandidateHypothesis` values.
- `DeterministicHypothesisValidator` checks Fact existence, duplicate references,
  entity consistency, and required code-change support.
- A code-change candidate requires both a changed-file Fact and a matching
  failure-file/hunk Fact for the same file-path subject.
- Empty candidates and no accepted hypotheses are valid outcomes.

## Invariants

- LLM output is never an authoritative Fact or final prose answer.
- Fact identifiers are necessary but not sufficient: their selected Fact
  families must satisfy the candidate predicate.
- No rule branches on Redis, Postgres, Kafka, or another named technology.
- Provider failure, outer response failure, candidate-schema failure, and
  deterministic rejection remain distinct.

## Deferred

- Dependency and deployment causal families, because the current Fact taxonomy
  cannot establish their required generic support relationships.
- Contradiction handling, because no current Fact expresses hard counter-evidence.
- Deterministic wording, because V2.19 owns grounded rendering.
- LLM judging, numeric scoring, causal graphs, and a large taxonomy.

## Validation

Run focused generator/validator tests, compilation, full backend discovery, and
diff checks. Complete the mandatory teaching-comment pass after initial tests.

## Completion

The focused suite passed six tests. `uv run python -m compileall -q app tests`,
the full backend unittest discovery (339 passing, six PostgreSQL skips without
`TEST_DATABASE_URL`), and `git diff --check` passed after the final teaching
comment pass.
