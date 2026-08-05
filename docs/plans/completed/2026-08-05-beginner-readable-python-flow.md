# Execution plan: Beginner-readable Python execution flow

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-05
- Last updated: 2026-08-05
- Related ADRs: ADR-002, ADR-003, ADR-004, ADR-005, ADR-006, ADR-007
- Related tasks: None

## Objective

Make the existing FastAPI merge-readiness execution path substantially easier
for a Python beginner with a Node.js/TypeScript background to read from
application assembly through HTTP, workflow, connectors, policy, runtime state,
persistence, and response handling without changing observable behavior.

## Current behavior and evidence

`app/main.py` creates application-scoped connectors and owns their cleanup in a
FastAPI lifespan. `connector_router.py` retrieves application dependencies and
delegates the readiness request to `MergeReadinessWorkflowService`. The workflow
persists a pending run, a running run, three ordered steps, connector facts, and
an atomic terminal policy-step/run snapshot. PostgreSQL uses short SQLAlchemy
transactions and conditional status updates. Telemetry reports terminal facts
only after the corresponding save succeeds.

The pre-refactor command
`uv run python -m unittest discover -s tests -v` ran 112 tests successfully;
four guarded PostgreSQL tests skipped because `TEST_DATABASE_URL` was absent.

## Proposed behavior

Preserve the same behavior while making the reading path explicit:

```text
create application resources
-> lifespan startup
-> validated route input
-> injected workflow
-> create and start run
-> fetch and persist GitHub facts
-> fetch and persist Jira facts
-> evaluate policy
-> atomically persist terminal result
-> translate terminal run to HTTP
-> lifespan shutdown
```

## Scope

- In scope: internal control flow, local helper boundaries, descriptive names,
  beginner-focused comments, tests that protect preserved behavior, learning
  documentation, and a detailed local Mermaid flow.
- Expected systems and files: existing files under `services/api/app`, focused
  backend tests, `docs/learning/LEARNING-LOG.md`, and `docs/mermaid`.

## Non-goals

- No route, JSON contract, HTTP status, state transition, policy, database,
  migration, connector mode, dependency, framework, or deployment changes.
- No folder or file renames and no whole-repository rewrite.

## Acceptance criteria

- [x] `main.py` makes import, assembly, startup, request, and shutdown timing clear.
- [x] HTTP routes read as validated input, service call, and HTTP output.
- [x] The workflow's top-level method exposes the complete business sequence.
- [x] Runtime transitions and persistence checkpoints remain explicit.
- [x] Connector ownership, fake/live selection, and policy purity remain intact.
- [x] Existing observable tests and configured checks pass at the same capability.

## Invariants

- Public routes, JSON shapes, and HTTP status behavior do not change.
- Runs and steps keep their existing state transitions, names, ordering, and
  first-attempt behavior.
- Connector and policy work occurs outside database transactions.
- Terminal policy step plus completed run, and failed step plus failed run, each
  commit atomically before HTTP reports the terminal state.
- Live connectors never fall back to fixtures and secrets never enter errors or
  telemetry.
- Observability remains best effort and terminal reporting follows persistence.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Connector unavailable | Completed `unknown` unless another blocker is known | Restore provider and retry |
| Connector or policy exception | Sanitized, durably stored failed run and HTTP `500` | Inspect safe telemetry and retry after correction |
| Persistence unavailable | Sanitized HTTP `503`; no unconfirmed terminal claim | Restore database and retry |
| Concurrent state conflict | Typed HTTP `409` | Reload durable state before retrying |
| Invalid stored record | Sanitized HTTP `500` | Repair data through an authorized operational process |

## Security

Pydantic remains the HTTP and provider-data validation boundary. Connector
credentials, raw provider responses, database details, and private exception
messages remain excluded from public errors and bounded telemetry.

## Observability

Existing FastAPI, workflow, connector, step, policy, persistence, metric, and
structured-event behavior remains. Refactoring must not move terminal reporting
before the durable save it describes.

## Milestones

1. Simplify application assembly and HTTP dependencies; focused API/startup tests pass.
2. Expose the workflow sequence through named operations; workflow and telemetry tests pass.
3. Clarify runtime, persistence, policy, and connector code where evidence shows accidental complexity; focused tests pass.
4. Run the complete validation set, synchronize learning/flow documentation, and self-review the final diff.

## Validation strategy

- `uv run python -m unittest tests.unit.test_application_startup_logging tests.integration.test_merge_readiness_api -v`
- `uv run python -m unittest tests.unit.test_merge_readiness_workflow tests.unit.test_runtime_observability -v`
- Focused state, repository, policy, and connector tests for files changed.
- `uv run python -m unittest discover -s tests -v`
- `uv run python -m compileall -q app tests`
- `git diff --check`
- PostgreSQL integration tests only when the guarded test settings are available.

## Progress

- [x] 2026-08-05: Guidance, architecture, ADRs, source, tests, and current diff inspected.
- [x] 2026-08-05: Pre-refactor backend baseline recorded: 112 tests, four guarded skips.
- [x] 2026-08-05: Application and HTTP pass complete; 13 focused tests passed.
- [x] 2026-08-05: Workflow pass complete; compilation and 20 focused tests passed.
- [x] 2026-08-05: Runtime, persistence, policy, and connector pass complete; 29 focused tests passed.
- [x] 2026-08-05: Documentation, validation, and review complete.

## Decisions and discoveries

- This is a Level 1 internal refactor. Existing accepted ADR boundaries and
  public contracts remain authoritative; no new architectural choice is needed.
- The largest accidental complexity is the workflow's repeated interleaving of
  business work, telemetry attributes, failure translation, and checkpointing.
- Classes remain appropriate for application-owned resources, connectors,
  repositories, telemetry, and the dependency-sharing workflow service.

## Risks and open questions

- Excessive helper extraction could replace one long function with a difficult
  call chain. Helpers must name complete business or lifecycle operations.
- Existing tests strongly cover behavior but the guarded PostgreSQL integration
  tests cannot run without an explicitly isolated test database.

## Completion

The behavior-preserving refactor, learning entry, and local Mermaid flow are
complete. Python compilation passed. Backend discovery ran 112 tests
successfully with four guarded PostgreSQL skips because `TEST_DATABASE_URL` was
absent. Seven frontend tests, the frontend build, Oxlint, and `git diff --check`
passed. Final review found no public contract, migration, state transition,
connector source, transaction, sanitization, or telemetry-order change.
