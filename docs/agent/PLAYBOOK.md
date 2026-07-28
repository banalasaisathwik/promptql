# Agent playbook

**inspect -> understand -> decide -> plan -> implement -> validate -> review ->
teach -> document**

1. **Inspect:** Read the closest `AGENTS.md`, [documentation
   index](../index.md), relevant code/tests, manifests, and Git diff.
2. **Understand:** State observable behavior, boundaries, constraints, and
   unknowns.
3. **Decide:** Classify choices. Resolve architectural choices with the owner
   and record them.
4. **Plan:** Define objective, behavior, files, invariants, failures, security,
   tests, non-goals, and unresolved decisions.
5. **Implement:** Make one logical, reviewable change and preserve unrelated work.
6. **Validate:** Run narrow checks first, then broader relevant checks; record
   exact commands and results.
7. **Review:** Inspect the final diff for correctness, compatibility, security,
   failures, observability, stale claims, and debug artifacts.
8. **Teach:** Explain flow, invariants, design, alternatives, trade-offs,
   failures, and validation.
9. **Document:** Update sources of truth and work records whose facts changed.

## Acceptance criteria

State the starting input, behavior or transition, observable result, and
relevant failure or permission behavior. Prefer “Given an unauthenticated
request, the API returns status X without exposing Y” to “authentication works.”

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
