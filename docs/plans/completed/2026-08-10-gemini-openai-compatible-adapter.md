# Execution plan: Gemini OpenAI-compatible explanation adapter

- Status: Completed
- Owner: Repository owner
- Created: 2026-08-10
- Last updated: 2026-08-10
- Related ADRs: ADR-011, ADR-012, ADR-013

## Objective

Use the existing OpenAI SDK with Gemini's documented compatibility endpoint
without weakening PromptQL's deterministic explanation boundary.

## Current and resulting behavior

Previously `gemini-2.5-flash` configured under OpenAI mode was sent to OpenAI's
default endpoint and failed. Explicit Gemini mode now reads `GEMINI_*` settings,
uses a fixed Google endpoint and Chat Completions structured parsing, then hands
the same typed claims to the existing validator and templates.

A live smoke test later showed Google rejects the complete enum schema. ADR-014
records the implemented compact request-local index contract that maps provider
positions back to typed codes before the unchanged validator.

## Scope and non-goals

The bounded change covers configuration, provider factory, adapter, telemetry
allowlist, mocked tests, environment example, architecture/decision/testing
documentation, learning log, and ignored Mermaid flow. It does not change the
policy, route, response schema, frontend, database, retries, fallback, or
explanation persistence.

## Invariants, failure behavior, and security

The policy result remains authoritative; generated prose is discarded; secrets,
payloads, and raw errors remain excluded. Missing configuration fails startup.
Authentication, quota, network, refusal, malformed-output, and upstream failures
produce the existing sanitized explanation error without changing the run.
Fixing Google's base URL in code prevents arbitrary credential forwarding.

## Validation strategy

Run focused provider/configuration/explanation tests first, then complete backend
discovery, Python compilation, configured frontend tests/lint/build, diff checks,
and a final secret/API/persistence review. Automated validation must not contact
OpenAI or Google.

## Completion

Implementation and documentation are complete. Final command results are
recorded in the 2026-08-10 learning-log entry and task report.
