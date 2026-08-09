# ADR-008: Treat unknown Jira blocker metadata as optional V1 evidence

- Status: Accepted
- Date: 2026-08-09
- Owners: Repository owner
- Supersedes: ADR-007 only for the policy treatment of unknown blocker evidence
- Superseded by: None

## Context

The standard Jira Cloud issue endpoint has portable status-category facts but
no universal blocker field. The live connector therefore correctly preserves
`blocker_state=unknown`. The original ADR-007 consequence treated that value as
required missing evidence, so a pull request with satisfied GitHub requirements
and a done Jira issue could not reach `ready`.

`UNKNOWN` is neither proof of a blocker nor proof that no blocker exists.
Priority, issue links, and custom fields have different meanings across Jira
sites and cannot safely supply a universal replacement.

## Decision

- Jira blocker metadata is optional supplementary evidence in V1.
- `BlockerState.BLOCKED` remains a verified blocker.
- `BlockerState.NOT_BLOCKED` does not block.
- `BlockerState.UNKNOWN` remains recorded exactly in evidence references but
  adds no blocker, missing-information finding, or retry action.
- Normalized Jira completion status remains required evidence. Unknown required
  GitHub or Jira evidence still produces `unknown` when no blocker exists.
- Decision precedence remains verified blocker, then missing required evidence,
  then ready.

## Alternatives and trade-off

Requiring blocker evidence to be known was rejected because the standard live
connector could never produce `ready`. Treating `UNKNOWN` as `NOT_BLOCKED` was
also rejected because it would turn absence of evidence into a factual claim.

The chosen rule enables useful live V1 decisions without site-specific setup,
but it cannot detect blockers represented only by tenant-specific Jira fields
or conventions. A future configurable mapping would require validation,
authorization, versioning, and audit history.

## Compatibility and consequences

The correction changes only policy interpretation. Connector facts, API and
Pydantic models, runtime steps, JSONB persistence, frontend types, and telemetry
remain unchanged, so no migration is required. Existing redaction and
observability boundaries are unaffected.
