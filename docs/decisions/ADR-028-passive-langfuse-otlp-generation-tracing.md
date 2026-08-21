# ADR-028: Passive Langfuse tracing through OpenTelemetry

- Status: Accepted
- Date: 2026-08-21

## Context

The investigation runtime needs operator-visible stage timing and LLMOps
correlation across planning, hypothesis generation, and code diagnosis. The
repository already uses OpenTelemetry for application traces and metrics, while
Langfuse accepts OTLP traces. Runtime behavior must not depend on either hosted
destination, and observability must not export prompts, code, Evidence bodies,
provider responses, or credentials.

## Options considered

### Option A: Add the Langfuse SDK beside OpenTelemetry

This offers Langfuse-native APIs but adds a production dependency and a second
instrumentation path. The same generation could drift into two inconsistent
traces, and domain code would become more vendor-aware.

### Option B: Add a second OTLP trace exporter

The existing manual investigation spans remain authoritative instrumentation.
A failure-isolated exporter sends the same bounded trace to Langfuse's native
OTLP endpoint. Standard GenAI model and token attributes let Langfuse interpret
generation observations without receiving raw inputs or outputs.

### Option C: Export only to the general OTLP destination

Operators could configure an external collector to fan out traces. That is a
valid later deployment option, but it does not provide a minimal repository
configuration for direct Langfuse use and would make local setup depend on an
additional service.

## Decision

Choose Option B. `RuntimeTelemetry` creates one trace hierarchy for the whole
investigation and nested spans for each bounded stage. LLM stages carry safe
task, provider, requested/resolved model, prompt version, duration, token, and
failure metadata. `create_observability()` may attach an independent Langfuse
OTLP HTTP/protobuf span exporter to the same tracer provider. It does not attach
a Langfuse metric exporter and does not introduce a Langfuse SDK.

Configuration requires an HTTPS base origin, public key, and secret key when
enabled. Localhost HTTP remains available for a self-hosted development
instance. Credentials are excluded from settings representations and converted
to the required Basic authorization header only inside exporter setup.

PromptQL does not calculate a monetary cost. Langfuse may derive cost from the
standard model and provider-reported token attributes when its pricing catalog
recognizes that model. Unknown provider token usage or pricing remains unknown.

## Consequences

- Grafana/general OTLP and Langfuse can be enabled independently or together.
- One instrumentation path prevents trace hierarchy and redaction rules from
  diverging between destinations.
- An unavailable exporter disables its own export after a bounded warning and
  cannot change workflow state, persistence, or HTTP behavior.
- Direct export avoids a collector dependency now; a future deployment can
  replace fan-out topology without changing investigation code.
- Hosted Langfuse trace verification remains an external gate until valid
  project credentials are configured.

## Security and privacy

The span attribute allowlist excludes the investigation question, prompt text,
code excerpts, Evidence and Fact payloads, generated candidates, raw provider
responses, exception messages, endpoints, and authorization data. Run IDs are
allowed only for trace correlation and never become metric labels.

## Validation

Unit tests prove independent general-OTLP and Langfuse-only processor setup,
credential completeness and representation redaction, the official endpoint
and header shape, one correlated investigation trace, generation metadata,
bounded metrics, retry spans, and payload exclusion. The complete offline fake
trajectory exercises the same production workflow stages without external
credentials.

## Reconsideration triggers

Reconsider a native SDK only if a measured Langfuse feature cannot be expressed
through supported OpenTelemetry attributes, or introduce a collector when
deployment operations require centralized sampling, transformation, or fan-out.
