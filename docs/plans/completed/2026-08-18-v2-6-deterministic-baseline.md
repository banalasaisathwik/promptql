# Execution plan: V2.6 deterministic investigation baseline

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-18
- Related milestone: V2.6

## Objective

Execute a small fixed investigation runbook through the V2.5 read-only tools,
accumulate normalized evidence, and derive only deterministic cross-source
facts. The result deliberately contains no causal hypothesis or LLM output.

## Current behavior

V2.5 exposes seven typed read-only tool definitions and adapters, but its
registry is metadata only. V2.1/V2.2 provide immutable investigation results,
typed evidence, and a small fact union; no investigation workflow currently
collects evidence or derives relationships.

## Proposed behavior

1. A sequential baseline invokes registered tool adapters through a small
   dispatcher, with explicit conditional branches from typed evidence.
2. An accumulator preserves evidence order/provenance and rejects duplicate
   evidence identifiers.
3. Pure, focused derivation modules produce temporal, deployment/commit,
   commit/PR, changed-file/failure-file, and hunk/failure-line facts.
4. Tool failures become bounded missing-information records while usable
   evidence and facts remain in the result.

## Invariants and non-goals

- The registry remains discoverable metadata; the dispatcher owns invocation.
- Evidence collection does not create facts; derivation does not call sources.
- Facts cite every evidence identifier required by their predicate.
- Equal timestamps, missing patches, deleted/new-count-zero hunks, and absent
  associations produce no positive relationship fact.
- No planner, LLM, hypothesis generation, generic rule engine, retries,
  parallelism, persistence, API, or UI is included.

## Validation

Add focused derivation and workflow tests, then run the affected unit modules,
complete backend discovery, compilation, and diff hygiene. Finish with the
required code-teaching comment pass and repeat affected validation.

## Completion

- The deterministic baseline uses the V2.5 tool surface through a small
  `ToolInvoker`; the registry remains metadata-only.
- Focused derivation modules preserve evidence provenance and emit only positive,
  non-causal facts from explicit predicates.
- Canonical, repeated, partial-failure, branch-order, duplicate-evidence, and
  conservative temporal/code relationship tests pass without live credentials.
- Full backend discovery passes with only the guarded PostgreSQL tests skipped
  when `TEST_DATABASE_URL` is absent.
