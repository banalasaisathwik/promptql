# Execution plan: Explanation evals and prompt versioning

- Status: Active — Stage 2 verified offline; waiting for formal live-run approval
- Owner: Repository owner
- Created: 2026-08-11
- Last updated: 2026-08-11
- Related ADRs: ADR-011, ADR-012, ADR-013, ADR-014, ADR-015
- Related tasks: None

## Objective

Observe real configured LLM behavior across deterministic merge-readiness cases,
let the repository owner inspect those observations, and only then implement a
formal development/holdout eval system with stable prompt versioning.

## Current behavior and evidence

Fake GitHub and Jira connectors provide deterministic typed facts. The pure
`evaluate_merge_readiness()` function derives the authoritative policy result.
`build_explanation_input()` minimizes that result, a selected `LLMClient` returns
structured claims, and `StrictMergeReadinessExplanationValidator` rejects
unsupported, incomplete, duplicate, or contradictory codes. The application
returns only deterministic template wording and intentionally does not expose
the generated claims needed for eval inspection.

Automated adapter and explanation tests use injected clients or SDK doubles and
make no external calls. Application telemetry records bounded outcomes and token
counts but excludes prompts, output, configured models, and external identities.

## Implemented behavior

Stage 1 adds a manually invoked observation boundary:

```text
deterministic fixture-derived facts
-> deterministic policy result
-> production explanation input builder
-> configured production LLM adapter and parser
-> production deterministic validator
-> ignored local JSONL observation report
```

Stage 2 now formalizes `merge-readiness-explanation` version `v1`, separate
versioned development/holdout datasets, deterministic graders, three-sample
defaults, inter-request pacing without retry, explicit thresholds, compatible
baseline comparison, incremental observations, and aggregate reports. No Stage
2 real-provider development or holdout run has been executed.

## Scope

- In scope:
  - Eleven representative Stage 1 fixture-derived cases.
  - Explicit paid-call acknowledgement and fake-only dry-run mode.
  - Typed, sanitized local JSONL observations.
  - Shared deterministic required-claim derivation.
  - Offline tests that cannot open provider connections.
- Expected systems and files:
  - `services/api/app/evals`
  - `services/api/app/explanations/validator.py`
  - `services/api/tests/unit`
  - `services/api/app/evals/graders.py`, `reporting.py`, and `runner.py`
  - `.gitignore`, architecture/testing/learning documentation

## Non-goals

- No LLM-as-a-judge, hosted eval service, production traffic collection,
  database persistence, API/frontend change, prompt optimization, retry,
  fallback, RAG, agent eval, or live GitHub/Jira data.
- No Stage 2 implementation before Stage 1 observations are approved.

## Acceptance criteria

- [x] Stage 1 covers ready, each requested blocker family, unknown evidence,
      simultaneous blockers, and multiple actions.
- [x] Expected decision/reason/action codes are derived from production policy
      and validation logic rather than manually copied labels.
- [x] A real provider cannot be called without explicit paid-call acknowledgement.
- [x] Fake mode runs only with an explicit dry-run flag.
- [x] JSONL contains only the approved observation fields.
- [x] Automated tests use fake/injected clients and open no provider connection.
- [x] Exact live command, request count, and output-token cap are shown before
      the repository owner approves any paid calls.
- [x] Development and holdout datasets have stable disjoint IDs and derive
      deterministic expected claims from production policy behavior.
- [x] Repeated samples, pacing, separate attempt/candidate denominators,
      deterministic graders, thresholds, and per-development-case reliability
      are implemented.
- [x] Completed reports, compatible baselines, comparisons, aggregate-only
      holdout output, and explicit holdout debugging are implemented.
- [x] Automated Stage 2 tests construct no live client or network connection.

## Invariants

- Policy facts and expected outputs are deterministic; only the model call may
  vary.
- The existing parser and validator remain the production source of truth.
- Reports exclude prompts, generated prose, identities, payloads, secrets, raw
  responses, and raw exceptions.
- Application API, persistence, policy, runtime, and frontend behavior remain
  unchanged.

## Failure cases and recovery

| Failure | Observable behavior | Recovery or rollback |
| --- | --- | --- |
| Missing/invalid provider configuration | Command exits before creating a client or report | Correct local environment and rerun preflight |
| Paid-call acknowledgement absent | Command exits before any provider call | Review cost boundary and pass the explicit flag |
| Fake selected for live mode | Command exits with guidance to use dry-run | Select a real provider or use fake dry-run |
| Provider/parser failure | Row records only a sanitized category | Inspect configuration/category; rerun intentionally |
| Schema/validator failure | Row retains structured observed codes when safe and records failure category | Compare expected/observed claims during Stage 1 review |
| Process interruption | Already-written JSONL rows remain local | Start a new observation run; resume semantics are Stage 2 |

## Security

The runner uses the existing provider factory and secret-bearing settings but
never serializes settings, credentials, prompts, raw provider objects, connector
facts, repository/Jira identity, prose, or exception text. Output is constrained
to an ignored local directory. Model identity is permitted only in this local
eval artifact and does not enter the public API or application telemetry.

## Observability

Stage 1 records per-case latency and provider-reported token counts in the local
artifact. It does not emit new production telemetry or scrape application logs.
Failures use existing sanitized provider and validator categories.

## Milestones

1. Stage 1 controlled observation runner passes offline tests and pauses before
   live calls.
2. Repository owner approves and inspects one live sample per Stage 1 case.
3. Stage 2 formal eval datasets, graders, prompt versioning, thresholds, and
   baseline comparison are implemented and verified.

## Validation strategy

1. Focused eval unit tests.
2. Existing explanation/provider unit tests.
3. Complete backend discovery with guarded PostgreSQL skips reported exactly.
4. Frontend tests, lint, and production build to prove public behavior remains
   unchanged.
5. `compileall`, `git diff --check`, ignored-artifact verification, and a final
   sensitive-content review.

## Progress

- [x] 2026-08-11: Inspected fixtures, policy, adapters, validator, telemetry,
      tests, ADRs, and current documentation.
- [x] 2026-08-11: Implemented and verified Stage 1 without live calls. Focused
      observation tests passed 8 cases; complete backend discovery ran 170 tests with four
      guarded PostgreSQL skips. Frontend tests, lint, build, and Python
      compilation passed. Fake dry-run wrote 11 ignored records. Real-provider
      preflight validated Gemini configuration and reported zero calls and a 5,632-token
      maximum output cap.
- [x] 2026-08-11: Ran the explicitly approved Stage 1 Gemini observation once.
      Eleven sequential calls produced seven exact validator passes followed by
      four sanitized `rate_limit` provider failures. The failed calls produced
      no candidate output, so schema validation and claim validation did not
      run. No automatic retries or extra samples were attempted.
- [x] 2026-08-11: Implemented Stage 2 and verified it offline. Twenty-six
      focused eval tests passed; complete backend discovery ran 188 tests with
      four guarded PostgreSQL skips. A 33-sample fake development run passed
      all release thresholds. Gemini preflight reported 33 development calls
      with a 16,896-output-token cap and 18 holdout calls with a 9,216-token
      cap; both made zero external calls.
- [ ] Formal development and holdout provider runs require separate explicit
      approval. A baseline may be saved only from a completed Stage 2 run.

## Decisions and discoveries

- Stable identities are `merge-readiness-explanation`/`v1`,
  `merge-readiness-development-v1`/`v1`, and
  `merge-readiness-holdout-v1`/`v1`.
- Expected claims will come from a shared validator helper so eval labels cannot
  drift from acceptance behavior.
- No cost estimate is recorded because pricing is not explicitly configured and
  versioned in the repository.

## Risks and open questions

- Three samples per case remain a small experiment rather than a statistically
  strong reliability estimate.
- Inspected Stage 1 cases become development cases and cannot later be described
  as untouched holdout evidence.

## Completion

Stage 1 and offline Stage 2 implementation are complete. The plan remains
active until explicitly approved formal provider runs are reviewed and a
completed compatible baseline decision is made.
