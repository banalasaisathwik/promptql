# ADR-024: Grounded hypothesis proposals use deterministic relationship validation

- Status: Accepted
- Date: 2026-08-19

## Context

V2.16 produces normalized Evidence and deterministic Facts but cannot express a
bounded causal interpretation. A parsed LLM response alone cannot establish a
root cause, and the current Fact vocabulary supports code-change/failure-file
relationships but not generic dependency-failure relationships.

## Decision

Use the existing provider-neutral typed LLM interface solely to propose up to
three `CandidateHypothesis` records. Each has a generic kind, subject, and
mandatory Fact identifiers. A pure deterministic validator accepts a
`code_change_may_have_contributed` candidate only when selected Facts prove both
a changed file and a matching failure location for that same file-path subject.

Candidates with unknown, duplicate, mismatched, or insufficient Fact references
are rejected in stable input order. Empty proposals and zero accepted hypotheses
are valid. Generated rationale is non-authoritative and is not rendered.

## Consequences

The LLM may help propose an interpretation without controlling accepted state.
The rule is reusable for any file path and contains no provider or technology
literal. Current dependency/deployment causal kinds, hard contradiction rules,
numeric confidence, LLM-as-judge, and final rendering are deferred. V2.19 will
render only accepted structured hypotheses through deterministic templates.
