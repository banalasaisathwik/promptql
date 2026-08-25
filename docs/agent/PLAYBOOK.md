# Agent playbook

**inspect -> understand -> decide -> plan -> implement -> validate -> review ->
teach -> document**

1. **Inspect:** Read the closest `CLAUDE.md`, [documentation
   index](../index.md), relevant code/tests, manifests, and Git diff. Identify
   whether the requested feature already partially exists, what should be
   reused rather than recreated, and the active V1/V2 milestone boundary
   (check [ARCHITECTURE.md](../ARCHITECTURE.md) Part 3, not memory).
2. **Understand:** State observable behavior, boundaries, constraints, and
   unknowns.
3. **Decide:** Classify choices. Resolve architectural choices with the owner
   and record them. See [Decision levels](#decision-levels) below.
4. **Plan:** Define objective, current behavior, proposed behavior, files,
   invariants, deterministic vs probabilistic responsibilities, failures,
   security, observability implications, evaluation implications where LLM
   behavior changes, tests, non-goals, unresolved decisions, and a
   DO NOW / POSTPONE / ADVANCED scope split where useful.
5. **Implement:** Make one logical, reviewable change and preserve unrelated work.
6. **Validate:** Run narrow checks first, then broader relevant checks; record
   exact commands and results. For a bug fix, reproduce the failure before
   changing implementation whenever practical. Report pass/fail/skip
   explicitly — never claim "all tests pass" without command evidence. Test
   invalid states as seriously as valid construction for domain models; test
   provider failure, schema failure, validator rejection, and success
   separately for LLM features.
7. **Review:** Inspect the final diff for correctness, compatibility, security,
   failures, observability, stale claims, and debug artifacts. See
   [Review checklist](#review-checklist) below.
8. **Teach:** Explain flow, invariants, design, alternatives, trade-offs,
   failures, and validation.
9. **Document:** Update sources of truth and work records whose facts changed.

## Review checklist

Beyond correctness, compatibility, security, failures, observability, stale
claims, and debug artifacts, check the final diff for: race conditions;
probabilistic output accidentally becoming authoritative; unnecessary
abstractions or speculative future architecture; weak or misleading tests;
and inconsistent V1/V2 documentation (a planned behavior described as already
implemented).

## Acceptance criteria

State the starting input, behavior or transition, observable result, and
relevant failure or permission behavior. Prefer “Given an unauthenticated
request, the API returns status X without exposing Y” to “authentication works.”

## Decision levels

- **Level 0 (mechanical):** applying an existing naming convention,
  formatting, adding an import, following an established test pattern,
  correcting an obvious typo. Make the decision directly without
  interrupting the user.
- **Level 1 (local design):** choosing a helper-function boundary, selecting
  between two equivalent local implementations, deciding where private logic
  belongs inside one module, naming an internal type. Briefly explain the
  decision and its local trade-off; proceed when it follows existing
  repository conventions.
- **Level 2 (architectural or high-impact):** adding a production
  dependency, changing a public API, changing the database schema,
  introducing a service/queue/cache/framework, defining
  authentication/authorization boundaries, choosing a concurrency or retry
  model, changing persistent state/event formats, creating a shared
  abstraction used across domains, changing deployment architecture,
  changing an authoritative deterministic/LLM boundary, introducing a new
  provider-facing protocol, or making a difficult-to-reverse domain-model
  decision. Do not implement immediately. Explain the concrete problem and
  constraints, present two to four realistic options with concrete
  trade-offs, ask the owner to choose and explain their reasoning when a
  choice is genuinely unresolved, evaluate that reasoning, provide a
  recommendation, record the resolved decision in an ADR when appropriate,
  and implement only after the decision is resolved. Do not reopen decisions
  already explicitly resolved unless new evidence materially changes the
  trade-off.

For a Level 2 decision, consider only dimensions that materially apply:
correctness, implementation complexity, operational complexity, failure
behaviour, security, performance, latency, scalability, testability,
observability, maintainability, migration difficulty, reversibility,
vendor/framework coupling, cost, learning value, deterministic/probabilistic
boundary, evaluation difficulty. Avoid generic claims such as "Option A is
more scalable" — explain what specifically scales, which resource or
bottleneck changes, under what workload, what new complexity is introduced,
and when the difference becomes relevant. Use "not materially relevant"
where a dimension does not apply.

## Choosing an artifact

- An **ADR** records a resolved, durable architectural decision.
- An **active task** tracks one bounded implementation.
- An **active execution plan** coordinates cross-layer, migration, high-risk,
  multi-session, or otherwise staged work.

Use the [ADR template](../decisions/ADR-TEMPLATE.md), [task
template](../tasks/TASK-TEMPLATE.md), or [execution plan
template](../plans/EXEC-PLAN-TEMPLATE.md). One record may link to another; they
are not interchangeable.

## Independent review

For high-impact or wide diffs, use a fresh agent context after implementation.
Provide the objective, criteria, decisions, and diff without the implementer’s
conclusions. Ask for correctness, boundary, failure, test, and documentation
findings. The implementer must verify and resolve the findings.

## Evidence standard

Do not call a system “enterprise-ready,” “scalable,” “secure,” or
“production-ready” without evidence. State the relevant workload, boundary,
failure behavior, measurements, tests, and operational mechanisms. Ground all
explanations in actual files, functions, commands, and diff locations.
