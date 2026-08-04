# ADR-005: OpenTelemetry observability with Grafana Cloud OTLP export

- Status: Accepted
- Date: 2026-08-04
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

Runtime runs and steps are durable, but operators cannot yet connect an HTTP
request to workflow timing, connector and policy latency, or persistence
failures. Observability must describe committed runtime truth without becoming
a business dependency or exposing connector data and credentials.

## Decision drivers

- Preserve runtime, policy, persistence, and HTTP semantics
- Correlate HTTP, workflow, step, and persistence work in one trace
- Emit terminal measurements only after the terminal commit succeeds
- Keep metric dimensions bounded and safe to aggregate
- Prevent exception, credential, SQL, request, and provider-payload leakage
- Remain portable if the hosted observability provider changes
- Keep ordinary unit tests deterministic and credential-free

## Decision

- Use OpenTelemetry traces and metrics, with FastAPI instrumentation only for
  the outer `SERVER` span and small manual `INTERNAL` spans for workflow,
  connector, policy, and repository operations.
- Export traces and metrics through OTLP HTTP/protobuf. Grafana Cloud is the
  current hosted destination, configured only through environment variables;
  no Grafana SDK or API appears in domain code.
- Use one application-scoped tracer provider, meter provider, bounded batch
  span processor, and periodic metric reader. Application lifespan shuts them
  down; requests never force a flush.
- Use standard Python logging for deterministic JSON events. OpenTelemetry log
  export is deferred.
- Keep `RunRepository` implementations telemetry-independent. An
  `ObservedRunRepository` decorator adds spans and failure measurements while
  preserving wrapped return values and exceptions.
- Use explicit closed persistence checkpoints rather than inspecting arbitrary
  run payloads to infer transition meaning.
- Use no-op telemetry for ordinary unit tests and in-memory OTel exporters and
  readers for observability tests.

## Trace hierarchy

```text
FastAPI request (SERVER)
`-- merge_readiness.execute (INTERNAL)
    |-- runtime.persistence.save
    |-- merge_readiness.github.fetch
    |-- merge_readiness.jira.fetch
    |-- merge_readiness.policy.evaluate
    `-- runtime.persistence.save
```

Repeated persistence spans carry a bounded checkpoint such as `run_created`,
`step_started`, or `run_completed`. Health requests and low-value ASGI
send/receive spans are excluded. W3C trace context remains the propagation
format supplied by OpenTelemetry instrumentation.

## Metrics and cardinality

| Instrument | Type | Allowed labels |
| --- | --- | --- |
| `promptql.workflow.runs` | Counter | workflow name/version, terminal run status |
| `promptql.workflow.run.duration` | Histogram, seconds | workflow name/version, terminal run status |
| `promptql.workflow.step.duration` | Histogram, seconds | workflow name/version, step name/outcome |
| `promptql.workflow.step.failures` | Counter | workflow name/version, step name, failure category |
| `promptql.runtime.persistence.failures` | Counter | persistence operation, failure category |

The code validates the exact label-key set for every instrument. IDs, trace
identifiers, repository input, PR numbers, exception messages, URLs, hosts,
SQL, and arbitrary strings are forbidden metric labels. This avoids a new time
series for every request and prevents sensitive values entering metric storage.

## Business outcomes and durable terminal telemetry

`ready`, `blocked`, and `unknown` are successful policy outcomes: the runtime
is completed and its workflow span is not an error. Connector exceptions,
policy exceptions, and persistence failures are system failures and receive a
closed sanitized category.

Terminal workflow metrics and JSON events are emitted only after the terminal
repository save returns. If that commit fails, the workflow emits neither a
completed nor failed terminal measurement. It records a persistence failure,
marks the workflow span with a sanitized error category, and preserves the
existing `503` behavior.

## Redaction and failure isolation

Only allowlisted bounded span attributes and JSON fields are accepted. Span
context managers disable automatic exception recording and automatic error
status. Code sets only `error.type`; it never records the exception object or
message. Header and body capture are disabled, and SQLAlchemy is not
instrumented.

Exporter calls are wrapped so exceptions become one bounded warning per signal.
OTLP exporter internal loggers are suppressed because their network messages
may contain destinations or raw error details. Telemetry setup or export
failure degrades to safe no-op OTel behavior and cannot change a workflow,
repository result, or HTTP response.

## Alternatives considered

- **Custom logs and timers only:** fewer dependencies, but no standard trace
  context, span hierarchy, or portable metric export.
- **Direct Sentry or Datadog SDK:** capable hosted products, but domain
  instrumentation and configuration would be more vendor-coupled.
- **Zero-code OpenTelemetry only:** useful for HTTP/process visibility, but it
  cannot express runtime steps, durable commit semantics, or bounded domain
  failure categories accurately.
- **SQLAlchemy automatic instrumentation:** provides query spans, but adds high
  volume and possible SQL detail without improving current run diagnosis.
  Explicit repository checkpoints are safer and clearer.

## Consequences

- Operators can correlate an HTTP request, run ID, workflow, steps, and storage
  checkpoints without storing full business inputs in telemetry.
- Background batching reduces request latency, but recent telemetry can be lost
  on abrupt process exit and exporter queues are intentionally bounded.
- Grafana Cloud can be replaced by another OTLP-compatible backend through
  configuration, though dashboards and backend-specific queries remain
  operational work.
- OpenTelemetry adds production dependencies and FastAPI instrumentation is
  currently distributed on the contrib beta version line.
- Dashboards, alerts, collector deployment, OTLP log export, SQL tracing, and
  cross-process workflow tracing remain deferred.
