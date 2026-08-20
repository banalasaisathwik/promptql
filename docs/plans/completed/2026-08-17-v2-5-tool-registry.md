# Execution plan: V2.5 tool abstraction and registry

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-17
- Related milestone: V2.5

## Objective

Expose a small provider-neutral read-only investigation tool surface over the
existing V2.3 GitHub code evidence, V2.4 IncidentSource, and Jira capabilities.
Make definitions typed and discoverable without coupling the domain to an LLM
provider, MCP, or the future execution runtime.

## Implemented in this plan

- Seven stable tool IDs: `get_commit`, `get_pull_request`, `get_diff`,
  `get_incident`, `get_deployments`, `query_telemetry`, and `get_jira_issue`.
- Strict Pydantic input models and provider-neutral `ToolResult` evidence
  output.
- Deterministic registry registration, lookup, and sorted discovery.
- Adapters that validate arguments before calling capabilities and sanitize
  typed source failures.
- Jira result normalization into the existing V2 evidence envelope.

## Decisions and invariants

- Tool identity is stable metadata, not a Python implementation name.
- The registry stores/discovers definitions; it does not execute handlers.
- Provider capabilities and planner-visible tools are separate abstractions.
- Results contain normalized `Evidence`, not model-generated conclusions.
- All V2.5 tools are read-only.
- Failure-location remains an IncidentSource capability, not a separate initial
  tool, because it is subordinate detail rather than an independent chooser
  action.
- Invalid arguments fail before source execution; unknown and duplicate tool
  IDs are explicit registry errors; capability unavailability and source
  failure remain distinct from an observed empty result.

## Validation

Validation completed with:

- `.venv\\Scripts\\python.exe -m unittest tests.unit.test_tool_registry` — 14
  passed.
- `.venv\\Scripts\\python.exe -m unittest discover -s tests -p "test_*.py"` —
  297 passed; 6 PostgreSQL tests skipped because `TEST_DATABASE_URL` is absent.
- `.venv\\Scripts\\python.exe -m compileall -q app tests` — passed.
- `git diff --check` — passed with only repository line-ending warnings.

The final code-teacher-comments pass processed the four tool Python modules and
the focused tool test; comments preserved executable behavior and all affected
validation was rerun afterward.

## Non-goals

No LLM planner, native provider tool calling, runtime executor loop, dynamic
gating, budgets, retries, checkpointing, replanning, MCP, write tools, fact
derivation, hypothesis generation, API route, or UI is part of V2.5.
