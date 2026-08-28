# ADR-032: Read-only Sentry REST incident connector

- Status: Accepted
- Date: 2026-08-28
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

`IncidentSource` (`app/connectors/protocols.py`) has had exactly one
implementation since it was introduced: `FakeIncidentSource`
(`app/connectors/incident_fakes.py`). A prior read-only diagnostic confirmed
Sentry's REST API (issue detail, latest event, releases, deploys,
events-stats) is a workable live source for all four `IncidentSource`
methods, following the same fake/live-switching pattern already established
for GitHub (`ADR-006`) and Jira (`ADR-007`). Building the connector surfaced
two field-level gaps the diagnostic had already flagged as needing an
explicit decision rather than a guess, plus one gap discovered only while
implementing `get_deployment_evidence`.

## Decision drivers

- Never let a connector invent a fact to satisfy a required field
  (`app/investigations/CLAUDE.md`: represent uncertainty explicitly instead
  of fabricating it).
- Preserve the existing fake/live independence and no-fallback posture used
  by every other connector: a live failure must never silently return
  fixture data.
- Keep the demo/portfolio use case realistic given Sentry's free-tier limits
  rather than assuming unlimited retention or quota.
- Reuse established connector conventions (typed error taxonomy, two-stage
  response validation, per-call observability) rather than inventing new
  ones for one more provider.

## Options considered

### `IncidentEvidenceContent.environment` / `.category`

Both fields are optional. Sentry never returns `environment` on an issue
object (it is only an accepted query filter, not a response attribute), and
nothing in Sentry's issue schema (`level`, `issueType`, `issueCategory`) is
an honest match for a status-code-style category like `"http_5xx"`.

- **Option A (chosen): always `None`.** Leave both fields unset for every
  Sentry-sourced `IncidentEvidenceContent`.
- **Option B: passthrough-unverified.** Echo back whatever `environment`
  string a caller supplied as a query filter, as if Sentry had confirmed it.
  Rejected: nothing on the response validates that the returned issue
  actually belongs to that environment.
- **Option C: heuristic parsing.** Derive `category` from free-text fields
  (`metadata.value`, `title`, `culprit`). Rejected: this is pattern-matching
  dressed up as a fact, exactly what "represent uncertainty explicitly
  instead of inventing facts" forbids.

### Issue `status` -> `IncidentStatus`

Sentry issues report `status` as `unresolved`, `resolved`, or `ignored`.

- **Decision:** `unresolved` -> `ACTIVE`, `resolved` -> `RESOLVED`,
  `ignored` -> `UNKNOWN`. `ignored` is not a faithful match for either
  `ACTIVE` or `RESOLVED` — an ignored issue is deliberately silenced, not
  known to be fixed or ongoing — so `UNKNOWN` is the honest mapping rather
  than a guess in either direction.

### `deployment_reference` for `get_deployment_evidence`

`DeploymentEvidenceContent.environment`, `.service`, and `.deployed_at` are
all **required** (non-optional) fields — a different gap than the one above,
discovered only while implementing this method. A bare Sentry release object
has none of them reliably: no `environment` attribute at all, `dateReleased`
can be null, and `projects[]` can be empty. Sentry's release-scoped Deploys
resource (`GET /organizations/{org}/releases/{version}/deploys/`) does carry
a real `environment` and a populated `dateFinished` per deploy — but a
release can have zero, one, or several deploys, one per environment, so the
release version alone cannot select one deploy unambiguously.

- **Option A: version only, require exactly one deploy.** Keep
  `deployment_reference` as a bare release version; if the release's deploy
  list has exactly one entry, use it, otherwise raise a typed ambiguity
  error. No encoding convention needed, but silently breaks the moment a
  release is deployed to a second environment.
- **Option B (chosen): composite `"version:environment"` reference.**
  `deployment_reference` is parsed as `version:environment` (split on the
  last colon, since environment slugs never contain colons but a release
  version theoretically could). This resolves a specific deploy
  unambiguously regardless of how many environments a release has been
  deployed to.
- This required checking `DeploymentEvidenceRequest.deployment_reference`
  and every other use of `deployment_reference` across the codebase
  (`app/connectors/models.py`, `app/investigations/models.py`,
  `app/tools/models.py`, `app/investigations/grounding_extraction/models.py`)
  before adopting Option B: every occurrence uses the unconstrained
  `NonEmptyString` type (no regex, no required prefix). The fixture's
  `"deployment:1042"` shape is a fixture-authoring convention, not a
  validated format, so `"checkout@1.0.0:production"` is a valid value
  today with **no schema or validator change** anywhere in the codebase.

### Free-tier demo fragility

Sentry's Developer (free) plan gives 30-day issue/event retention, a 5,000
error/month quota, and a single user seat. Unlike GitHub/Jira fixtures (or
even live GitHub/Jira objects, which are durable indefinitely), a live
Sentry issue used for verification will age out of retention and demo
traffic can exhaust the monthly quota.

- **Decision:** treat live Sentry as a one-time, deliberately captured proof
  of correctness, not an always-on demo path. `PROMPTQL_SENTRY_CONNECTOR`
  defaults to `fake` for all ongoing development and demos; a real account
  is used once to exercise all four methods, the request/response is
  captured (token redacted) as a permanent record, and the connector mode
  is reset to `fake` immediately afterward.

## Decision

Add `HttpSentrySource` (`app/connectors/sentry_http.py`) implementing
`IncidentSource` directly, with no shared HTTP base class — Sentry's cursor
(`Link`-header) pagination is structurally unlike GitHub's page-number
scheme, and none of the four `IncidentSource` methods needs list pagination
at all (each fetches by direct reference: one issue, one event, one release,
one bounded deploy list, one stats window), so `HttpSentrySource` mirrors
`jira_http.py`'s self-contained single-purpose shape rather than
`github_http_base.py`'s shared-pagination shape.

`environment` and `category` on `IncidentEvidenceContent` are always `None`
for Sentry-sourced evidence (Option A above). `deployment_reference` is a
`"version:environment"` composite (Option B above). Issue status maps
`unresolved/resolved/ignored` -> `ACTIVE/RESOLVED/UNKNOWN`. Windowed event
counts are computed by summing Sentry's `events-stats` time-bucket response
(`{"data": [[timestamp, [{"count": n}, ...]], ...]}`) rather than assuming
any endpoint returns a single scalar count. Only `TelemetrySignal.ERROR_EVENTS`
has a verified Sentry Discover query mapping (`event.type:error`);
`LOG_EVENTS` and `TRACE_ERRORS` are rejected with a typed error before any
HTTP call rather than guessed at.

Implementing this surfaced two error cases the original taxonomy sketch
(`SentryUnauthorizedError`/`SentryNotFoundError`/`SentryRateLimitedError`/
`SentryTimeoutError`/`SentryUpstreamUnavailableError`/
`SentryInvalidResponseError`/`SentryConfigurationError`) did not anticipate,
added following the same `ConnectorErrorCategory` convention: `SentryForbiddenError`
(403, distinct from 401 the same way GitHub/Jira keep them distinct),
`SentryReleaseMissingCommitError` (a release with a null `lastCommit` — a
clear typed error rather than constructing `DeploymentEvidenceContent` with
a fabricated commit SHA), `SentryInvalidDeploymentReferenceError` (malformed
`version:environment` input, validated before any HTTP call), and
`SentryDeployNotFoundError` (zero or multiple deploys match the requested
environment) and `SentryUnsupportedTelemetrySignalError` (see above).

`evidence_id` values (the `InvestigationIdentifier`-constrained field) are
built from a SHA-256 digest wherever the source string is free text that
could contain characters outside `[A-Za-z0-9._:-]` — release version,
environment name, `incident_reference`, `service` — mirroring
`github_code_http.py`'s existing `_digest()` precedent for the same reason
(repository names and file paths are free text too). `EvidenceProvenance
.source_reference` (unconstrained) keeps the human-readable form.

Live verification (see Validation) additionally caught a field-name error:
`SentryStackFrameResponse` originally used snake_case `lineno`, taken from
`develop.sentry.dev`'s SDK-to-Sentry *ingestion* payload spec rather than
the REST API's actual response shape. Sentry's REST API serializes this
field as camelCase `lineNo` — every mocked test used the same wrong
assumption, so nothing caught it until a real captured event did. Fixed to
`lineNo`, matching every other raw-response field in this file that already
keeps Sentry's actual camelCase key as the attribute name.

## Consequences

- `IncidentSource` gains its first live implementation; `FakeIncidentSource`
  remains the default for both `InvestigationWorkflowService` and every
  test that does not explicitly wire live mode.
- `PROMPTQL_SENTRY_CONNECTOR`, `SENTRY_TOKEN`, `SENTRY_ORGANIZATION_SLUG`,
  `SENTRY_API_BASE_URL`, `SENTRY_REQUEST_TIMEOUT_SECONDS` are new
  environment variables, independent of GitHub/Jira mode, following the
  existing independent-source-selection posture (ADR-007).
  `structured_logging.ALLOWED_EVENT_FIELDS` gained `sentry_source` so
  startup logging can report the selected mode alongside `github_source`/
  `jira_source`.
- Callers that want deployment evidence must know a specific Sentry
  environment, not just a release version — this is a real constraint on
  how `deployment_reference` gets constructed upstream (grounding
  extraction, tools), not just an internal connector detail.
- Sentry demo data is not durable the way GitHub/Jira fixtures or even live
  GitHub/Jira objects are; live verification is a point-in-time artifact,
  not a standing integration test.

## Invariants

- `HttpSentrySource.source` is always `ConnectorSource.LIVE`; it is never
  selected when `PROMPTQL_SENTRY_CONNECTOR` is `fake`.
- `IncidentEvidenceContent.environment` and `.category` are `None` for every
  `HttpSentrySource`-produced incident evidence record, unconditionally.
- `get_deployment_evidence` never constructs `DeploymentEvidenceContent`
  with a null-derived or fabricated `commit_sha`; a release with no
  `lastCommit` raises `SentryReleaseMissingCommitError` instead.
- `get_telemetry_window_evidence` never calls Sentry for a `TelemetrySignal`
  outside `_SIGNAL_QUERY_FRAGMENTS`; unsupported signals fail before any
  HTTP request.

## Validation

`services/api/tests/unit/test_sentry_connector_factory.py` (6 tests):
fake-default mode, live-mode selection, bearer-token/timeout wiring,
missing-configuration errors, invalid organization slug, secret hiding from
`repr()`. `services/api/tests/unit/test_sentry_http_connector.py` (21
tests): success-path normalization for all four methods including the
never-fabricated `environment`/`category` fields, all three documented
status mappings, crash-frame selection (last frame, not first — Sentry
orders frames oldest-to-newest), the `lineNo` regression test (see below),
deploy-environment disambiguation, stats-bucket summation across multiple
buckets and multiple values per bucket, malformed-deployment-reference
rejection before HTTP, null-commit rejection, zero/multiple-matching-deploy
rejection, unsupported-signal rejection before HTTP, malformed-response
rejection, HTTP status taxonomy (401/403/404/429/5xx) sanitization, timeout
vs. network-failure distinction, `evidence_id` sanitization for unsafe
free-text characters (`EvidenceIdentifierSanitizationTests`), and
secret/input absence from telemetry spans and logs. Run:
`uv run python -m unittest discover -s tests -v` from `services/api`
(534 tests, 6 skipped, all passing as of this ADR).

Live verification against a real Sentry account was captured on 2026-08-28:
one real error triggered through the actual `sentry-sdk` (producing one
issue and one event), one release created through the Releases API with an
explicit commit (producing a real `lastCommit`), one deploy created for
that release. All four `IncidentSource` methods were run against this real
data through the connector's actual code, confirming `environment`/
`category` stayed `None`, the correct crash frame and line number, the
correct event count, and correct deploy-environment resolution. This pass
caught the `lineNo` field-name error described above. Token never printed,
logged, or committed. `PROMPTQL_SENTRY_CONNECTOR` was reset to `fake`
immediately after capture. Full record:
[LEARNING-LOG.md, 2026-08-28](../learning/LEARNING-LOG.md).

## Reconsideration triggers

Revisit the `environment`/`category` always-`None` decision if a future
milestone adds a validated way to confirm which environment an issue
actually belongs to (for example, cross-referencing issue tags rather than
trusting a caller-supplied filter) or a deterministic, non-heuristic
category taxonomy Sentry itself exposes. Revisit the `"version:environment"`
composite reference if a consumer needs to address a deploy that isn't
cleanly identified by that pair (for example, redeploying the same version
to the same environment twice). Revisit the free-tier demo-fragility
mitigation if this project moves to a paid Sentry tier or a self-hosted
instance with longer retention.
