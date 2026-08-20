# ADR-022: Static per-tool plan output contracts

- Status: Accepted
- Date: 2026-08-18
- Owners: Repository owner

## Context

V2.5 tools return generic `ToolResult` values containing evidence. V2.8 must
validate references such as `Ref(s1, "commit_sha")` before execution, but the
generic result shape cannot expose tool-specific field names or types.

## Decision

Each `ToolDefinition` declares a metadata-only `plan_output_model`. It lists
only safe, planner-visible fields which a future executor may expose. The
runtime `ToolResult`, adapters, provider payloads, and execution behavior stay
unchanged.

## Consequences

The validator can deterministically check output field existence and Pydantic
annotation compatibility without inspecting evidence payloads. V2.9 must later
define how actual evidence is projected into these declared outputs. This small
explicit contract is less flexible than arbitrary selectors, but it keeps plan
validation finite, testable, and free of a query language.

## Invariants

- Static output contracts do not execute tools or alter `ToolResult`.
- A reference outside the declared contract is rejected.
- Unknown compatibility is rejected rather than coerced.
