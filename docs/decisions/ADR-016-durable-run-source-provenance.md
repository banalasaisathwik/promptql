# ADR-016: Durable bounded source provenance

- Status: Accepted
- Date: 2026-08-12
- Deciders: Repository owner and implementation agent

## Context

GitHub, Jira, and explanation implementations are selected independently at
application assembly. Logs and spans identified connector sources, but a stored
run and `GET /v1/runs/{run_id}` could not answer which implementations supplied
that result. A generic metadata object would solve more future cases but would
weaken validation and create an unbounded persistence contract.

## Decision

Add an optional typed `RunSources` object to the runtime contract. GitHub and
Jira use the existing `fake | live` enum; explanations use the closed
`fake | gemini | openai` enum. Persist the three values in nullable relational
columns with database check constraints and return them additively from POST
and GET responses.

The workflow captures connector selections when it creates the pending run.
The HTTP response reports the explanation provider that performed its
read-time enrichment, because explanations are intentionally not persisted and
a later GET can run under different application configuration. Old rows with
all three columns null reconstruct with `sources=null`.

The frontend accepts missing or null provenance for backward compatibility,
displays known values, and labels absent values `unknown`. It also treats the
existing HTTP 500 body as a typed failed run, never as a policy `unknown`.

## Reason

Closed typed columns make provenance queryable, validate allowed values at both
Pydantic and PostgreSQL boundaries, and avoid storing secrets, model names,
URLs, account identity, or provider payloads. Nullable columns make the
migration additive and preserve existing rows.

## Alternative considered

A JSONB metadata column was rejected for V1. It would be more extensible, but
would introduce an unbounded generic contract, weaker database validation, and
speculative indexing questions. Persisting complete explanations was also
rejected because it changes explanation lifecycle and versioning beyond this
completion task.

## Trade-off

Three columns require a migration when another source family is introduced.
That deliberate friction keeps V1 provenance finite and reviewable. Because
explanations are generated at response time, the response provider can differ
from the provider stored when an older run was created; connector evidence
sources remain durable.

## Optimization

- Do now: closed source enums, nullable columns, response validation, failed-run
  rendering, and round-trip tests.
- Postpone: explanation persistence and historical provider/model snapshots.
- Advanced/scale-stage: a versioned execution-metadata schema only after
  multiple concrete provenance dimensions justify it.

## Consequences

- New runs expose source provenance without changing decision semantics.
- Pre-migration rows remain readable.
- No source value is accepted as an arbitrary string.
- The migration must be applied before starting the updated API.
