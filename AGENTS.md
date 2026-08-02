# PromptQL Repository Agent Instructions

## Project purpose

This repository is both:

1. A production-quality PromptQL-like enterprise analytics platform.
2. A learning project through which the repository owner develops strong skills in AI infrastructure, backend engineering, system design, runtime engineering, LLMOps, security, testing and agent-assisted development.

The goal is not only to produce working code. The repository owner must understand the important decisions behind the code.

Do not silently make significant architectural decisions.

## Repository map

* `apps/web`: Vite, React and TypeScript frontend.
* `services/api`: FastAPI and Python backend.
* `packages`: reusable TypeScript packages.
* `docs`: product, architecture, decision and learning documentation.
* `infra`: local and production infrastructure configuration.
* `scripts`: repository automation.
* `evals`: evaluation datasets and runners when introduced.

Bun manages JavaScript and TypeScript dependencies.

uv manages Python dependencies and environments.

Do not use Bun to manage Python dependencies or uv to manage TypeScript dependencies.

## Before starting any task

Before editing files:

1. Inspect the relevant source files.
2. Read the closest applicable `AGENTS.md`.
3. Read `docs/index.md`.
4. Read relevant architecture documents and ADRs.
5. Inspect existing tests and nearby implementation patterns.
6. Check the current Git diff so unrelated user work is not overwritten.
7. State the current behaviour before proposing a change.

Do not assume the repository structure or behaviour from filenames alone.

## Decision classification

Classify decisions into one of three levels.

### Level 0: Mechanical decision

Examples:

* applying an existing naming convention
* formatting
* adding an import
* following an established test pattern
* correcting an obvious typo

Make the decision directly without interrupting the user.

### Level 1: Local design decision

Examples:

* choosing a helper-function boundary
* selecting between two equivalent local implementations
* deciding where private logic belongs inside one module
* naming an internal type

Briefly explain the decision and its local trade-off. Proceed when it follows existing repository conventions.

### Level 2: Architectural or high-impact decision

Examples:

* adding a production dependency
* changing a public API
* changing the database schema
* introducing a service, queue, cache or framework
* defining an authentication or permission boundary
* choosing a concurrency or retry model
* changing persistent state or event formats
* creating a shared abstraction used across domains
* changing deployment architecture
* making an irreversible or difficult-to-migrate decision

Do not implement a Level 2 decision immediately.

Use the learning protocol:

1. Explain the concrete problem and constraints.
2. Present two to four realistic options without vague labels.
3. Ask the repository owner to choose and explain their reasoning.
4. Evaluate that reasoning.
5. Identify correct points, missing considerations and misconceptions.
6. Provide a recommendation and explain when another option would be better.
7. Record the resolved decision in an ADR.
8. Implement only after the decision is resolved.

Do not ask the user to reason about trivial or already-decided matters.

## Required decision analysis

For a meaningful design decision, consider only dimensions that materially apply:

* correctness
* implementation complexity
* operational complexity
* failure behaviour
* security
* performance and latency
* scalability
* testability
* observability
* maintainability
* migration difficulty
* reversibility
* vendor or framework coupling
* cost
* learning value

Do not produce generic claims such as “Option A is more scalable.”

Explain:

* what specifically scales
* what resource or bottleneck changes
* under which workload
* what complexity is introduced
* when the difference becomes relevant

Use “not materially relevant” where a dimension does not apply.

## Planning protocol

Before a non-trivial implementation, provide:

* objective
* current behaviour
* proposed behaviour
* files expected to change
* important invariants
* failure cases
* security implications
* test strategy
* non-goals
* unresolved decisions

For a cross-layer feature, migration, major refactor or task that cannot be safely understood as one bounded patch, create an execution plan following `docs/agent/PLAYBOOK.md`.

## Implementation rules

* Make one logical change at a time.
* Prefer small, reviewable diffs.
* Do not perform unrelated refactors.
* Do not introduce a production dependency without explaining why existing code or the standard library is insufficient.
* Preserve existing behaviour unless the task explicitly changes it.
* Validate external data at system boundaries.
* Keep security and tenant boundaries explicit.
* Represent important state transitions explicitly.
* Avoid hidden global state and import-time side effects.
* Do not catch exceptions without handling, transforming or reporting them meaningfully.
* Do not claim success before validation completes.
* Do not overwrite unrelated uncommitted work.

## Dependency proposal protocol

Before adding a dependency, report:

1. The exact problem it solves.
2. Why the standard library or existing dependencies are insufficient.
3. Maintenance and ecosystem maturity.
4. Security and supply-chain implications.
5. Runtime and bundle impact.
6. Whether it affects only development or production.
7. Lockfile changes.
8. Exit or migration strategy.

Wait for approval for production dependencies.

## Testing and validation

After making a change:

1. Run the narrowest relevant test first.
2. Run the relevant lint and type checks.
3. Run broader tests when the change affects shared behaviour.
4. Inspect the final Git diff.
5. Report the exact commands executed.
6. Report what passed, failed or was not tested.
7. Never state “all tests pass” unless the reported commands support that claim.

Tests should validate observable behaviour and important invariants, not merely mirror implementation details.

For bug fixes, reproduce the failure before changing the implementation whenever practical.

## Self-review

Before finishing, review the diff for:

* correctness errors
* race conditions
* missing error handling
* security boundary violations
* accidental public API changes
* backwards-compatibility issues
* unnecessary abstractions
* weak or misleading tests
* stale comments or documentation
* unrelated changes
* debug code
* sensitive information

## Teaching report

After every meaningful task, explain:

1. What changed.
2. The request-to-response or data flow.
3. The important invariant.
4. Why this design was selected.
5. Which alternatives were considered.
6. The concrete trade-offs.
7. Important failure modes.
8. How tests prove the behaviour.
9. Security and observability implications.
10. Behaviour at larger scale, when materially relevant.
11. What remains incomplete or uncertain.
12. One question or small exercise that tests the repository owner’s understanding.

Ground explanations in actual files, functions, commands and diff lines.

Do not provide vague textbook explanations disconnected from the implementation.

## Required learning-log update

After every meaningful task that implements or changes code, update
`docs/learning/LEARNING-LOG.md` before finishing. This is required even when the
same task also has a completed task record, ADR, execution plan, or detailed
teaching response.

Each new learning-log entry must be grounded in the implemented diff and include:

* the engineering concept learned
* important language, framework, or library syntax introduced by the change
* the implementation locations and validation commands that provide evidence
* the important design decision and why it was selected
* the invariant or failure behavior that future changes must preserve
* the concrete trade-off and any unresolved question

Do not turn the learning log into a file-by-file changelog or paste large code
blocks. Explain only syntax and decisions that improve the repository owner's
reusable understanding. For a trivial code change with no new reusable lesson,
add a concise entry stating what existing pattern was reinforced rather than
silently skipping the log.

## Source-code comments

Comments should explain:

* why a non-obvious choice exists
* invariants
* security boundaries
* concurrency assumptions
* failure handling
* unusual performance trade-offs
* compatibility constraints

Do not comment obvious syntax.

Long teaching explanations belong in the task response or documentation, not inside production source files.

## Documentation updates

Update documentation when a change modifies:

* architecture
* public behaviour
* commands
* setup
* operational procedures
* security boundaries
* data ownership
* important trade-offs

Create or update an ADR for significant decisions.

Do not rewrite historical ADRs to pretend the original decision was different. Supersede them with a new ADR.

Use [the documentation index](docs/index.md) to locate the current source of
truth. Follow [the agent playbook](docs/agent/PLAYBOOK.md) for non-trivial
planning, execution and review.

## Final response format

Use this order:

1. Result
2. Changed files
3. Design explanation
4. Validation performed
5. Risks or remaining gaps
6. Learning check

Keep simple tasks concise. Use the full teaching report only when the task contains meaningful engineering decisions.
