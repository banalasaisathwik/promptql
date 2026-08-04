# ADR-007: Read-only Jira Cloud REST connector with normalized status categories

- Status: Accepted
- Date: 2026-08-04
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

Merge-readiness has deterministic Jira fixtures but cannot obtain a real linked
issue. The connector must support custom Jira workflows without interpreting
arbitrary status names, mixing live and fake facts, exposing account secrets,
or coupling the workflow and policy to Atlassian response shapes.

## Decisions

### Key-based asynchronous contract

- **Decision:** `JiraConnector` is asynchronous and accepts the Jira key already
  extracted and validated through GitHub facts. Both fake and HTTP Jira satisfy
  that protocol.
- **Reason:** Issue identity is the only Jira input. The workflow can await
  network I/O while remaining independent of source and raw JSON.
- **Alternative considered:** Preserve synchronous lookup by the full
  `ConnectorRequest` or let Jira repeat title/body/branch extraction.
- **Trade-off:** Existing fake tests and orchestration needed async conversion,
  but provider ownership and sequencing are now explicit and independently
  testable.

### Jira Cloud REST v3 with email and API-token Basic auth

- **Decision:** Use one GET `/rest/api/3/issue/{key}` request through the
  application-scoped `httpx.AsyncClient`, requesting only `status`, `assignee`,
  and `resolution`. Basic auth uses account email plus API token over HTTPS.
- **Reason:** One documented endpoint supplies every currently required fact;
  the existing HTTP stack is sufficient and an Atlassian SDK adds no value.
- **Alternative considered:** OAuth, Forge/Connect, an Atlassian SDK, or Jira
  search.
- **Trade-off:** Email/token configuration is suitable only for this
  single-user V1. OAuth or an Atlassian app is required before multi-user or
  distributed credential ownership. A strict `*.atlassian.net` base URL avoids
  arbitrary outbound hosts but does not support custom-domain aliases.

### Category semantics instead of custom status-name rules

- **Decision:** Map Jira status-category keys `new`, `indeterminate`, and `done`
  to existing `TO_DO`, `IN_PROGRESS`, and `DONE` facts. Preserve status ID/name
  only as display evidence; the policy checks the normalized category.
- **Reason:** Administrators may name statuses “Ready for QA,” “Released,” or
  anything else, so name equality is not a portable completion rule.
- **Alternative considered:** Treat `status.name == "Done"` or non-null
  resolution as completion.
- **Trade-off:** Broad categories intentionally lose detailed workflow-stage
  distinctions. This is correct for the current policy and avoids site-specific
  configuration.

### Unknown standard blocker evidence

- **Decision:** Live Jira returns `BlockerState.UNKNOWN`. The standard issue
  endpoint has no universal blocker field, and the policy treats unknown
  blocker evidence as missing information while preserving any verified
  incomplete-status blocker.
- **Reason:** Priority “Blocker,” issue links, and custom fields represent
  different business meanings and cannot be substituted safely.
- **Alternative considered:** Assume not blocked, use priority, or inspect every
  custom field/link.
- **Trade-off:** A live done issue cannot produce `ready` until the repository
  chooses and configures a site-specific blocker source. It can still move from
  a verified Jira incomplete blocker to an otherwise-unknown result.

### Independent source selection and no fallback

- **Decision:** GitHub and Jira settings/factories select sources independently.
  MockTransport is test infrastructure, not an application mode. Live Jira
  failures use the existing failed-run semantics and never return fixtures.
- **Reason:** Every fact in one run must have unambiguous provenance and outages
  must not produce convincing fictional evidence.
- **Alternative considered:** Tie Jira mode to GitHub mode or fall back to fake
  Jira on `401`, `404`, or timeout.
- **Trade-off:** Operators must configure both connectors explicitly. Source is
  recorded in bounded step/connector spans rather than adding a public run and
  database migration in this milestone.

## Error, security, and observability boundaries

Malformed keys fail before HTTP. Configuration, `401`, `403`, ambiguous `404`,
`429`, timeout, transport, `5xx`, malformed JSON, and schema failures enter a
closed sanitized connector taxonomy. `Retry-After` is retained only as a safe
bounded integer; no retry is performed.

Email, token, Basic value, base URL, issue/project key, status name, assignee,
raw URL/body, provider messages, and headers are excluded from runtime errors,
logs, spans, metrics, and persistence. Connector spans contain only connector,
source, operation, result category, and HTTP status class.

## Persistence compatibility and consequences

Optional safe status identity/resolution fields and the new blocker enum value
fit the existing Jira JSONB snapshot. Defaults permit older snapshots to
reconstruct, so no Alembic migration is required. Automated tests use only
`httpx.MockTransport`; live smoke testing is manual and credential-controlled.

Comments, changelog, search, pagination, writes, retries, caching, Jira OAuth,
Atlassian apps, multi-tenant credentials, and site-specific blocker mapping are
deferred.
