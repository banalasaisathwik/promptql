# ADR-023: Bounded retry policy for read-only investigation tools

- Status: Accepted
- Date: 2026-08-19
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

V2.10 has a sequential tool-call budget, but V2.5 adapters collapse connector
errors into `source_failure` and V2.9 performs only one call per plan step.
The runtime therefore cannot distinguish a potentially transient provider
failure from a permanent failure, nor account for a retry as a separate
external operation.

All current V2.5 investigation tools are read-only. They return normalized,
sanitized `ToolResult` values rather than raw provider data.

## Decision drivers

- Avoid retrying failures that cannot recover without corrected credentials,
  permissions, arguments, configuration, or provider data.
- Bound call count, provider cost, and request latency.
- Keep one runtime owner for retries so SDK retry behavior cannot bypass V2.10.
- Keep the implementation testable without queues, persistence, or distributed
  coordination.

## Options considered

### Retry every failed tool result

This needs the least taxonomy work, but repeats invalid requests, missing
resources, and authorization failures. It wastes budget and can mask a
configuration or permission problem.

### Retry only typed transient categories in the executor

Adapters preserve their sanitized connector category. The executor retries only
rate limits, timeouts, and upstream unavailability, using one shared budget
counter. This is explicit and testable, while keeping adapter calls single-shot.

### Delegate retries to each provider SDK

SDKs may offer transport-specific retry behavior, but their hidden attempts
would not reliably consume V2.10 budget or share one policy across adapters.

## Repository owner reasoning

The repository owner confirmed the second option: retry only rate-limited,
timeout, and upstream-unavailable failures; attempt at most three times total;
wait one second and then two seconds; charge every attempt to V2.10 budget.

## Reasoning review

The selected categories are plausibly transient and the three-call cap prevents
one plan step from consuming an unbounded amount of provider capacity. Charging
the budget before each call makes the hard execution limit independent of
whether the provider later reports success or failure. No jitter is appropriate
for this small sequential learning slice, but synchronized production traffic
would need it.

## Decision

- Extend `ToolFailureCode` with existing connector categories and expose a
  deterministic `ToolFailure.retryable` property.
- Retry only `rate_limited`, `timeout`, and `upstream_unavailable` failures.
- `AgentExecutor` makes at most three total calls for one plan step, waiting
  one second before attempt two and two seconds before attempt three.
- Reserve V2.10 budget before every call, including retries. If no budget
  remains for a retry, stop immediately, keep the typed failure, and terminate
  later pending work as budget-exhausted.
- Keep adapter/SDK attempts single-shot; all current tools remain read-only.

## Consequences

- Tool failures now expose enough bounded semantics for a consistent retry
  decision without exposing provider exception text.
- A successful retry can consume more of the global budget than one successful
  call; `ExecutionStepState.attempts` makes this visible in execution state.
- Exponential waits increase completion latency by up to three seconds for a
  step that fails all three attempts. At the current five-step plan maximum,
  sequential execution limits the impact but does not make a latency SLA.
- No new dependency, database schema, API route, or provider protocol is added.
- Write tools, crash recovery, jitter, deadlines, telemetry metrics, and
  persisted retry history remain deferred. V2.13 must establish idempotency
  before retrying any side-effecting capability.

## Invariants

- A non-retryable failure never causes a second provider call.
- No retry attempt occurs without first consuming one V2.10 budget unit.
- A blocked step makes no provider call and has zero attempts.
- Retryability comes only from the closed failure code, never provider text.
- Retried calls reuse the V2.8-validated tool ID and typed arguments.

## Validation

`tests/unit/test_tool_registry.py` proves adapter category translation,
sanitization, and retryability. `tests/unit/test_agent_execution.py` proves
one-second/two-second backoff, three total attempts, success after retry,
non-retryable failure, and budget exhaustion before a retry. Broader backend
discovery and compilation provide regression evidence.

## Reconsideration triggers

Revisit this decision when external providers supply reliable retry-after
metadata, concurrent execution begins, live traffic needs jitter/deadlines,
tools can create side effects, or retry observability/persistence becomes an
operational requirement.
