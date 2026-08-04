# ADR-006: Read-only GitHub REST connector with explicit runtime modes

- Status: Accepted
- Date: 2026-08-04
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

Merge-readiness used complete deterministic GitHub fixture facts. The workflow
now needs real GitHub evidence without coupling domain policy to HTTP, changing
the fake scenarios, inventing protection requirements, or allowing live
failures to produce convincing fixture results.

## Decisions

### Shared asynchronous contract and application-boundary selection

- **Decision:** Both implementations satisfy the asynchronous
  `GitHubConnector` protocol. `GitHubSettings` and `create_github_connector()`
  select `fake` or `github` while assembling FastAPI.
- **Reason:** The workflow depends on behavior and normalized models, not an
  implementation. Network I/O can yield control instead of blocking FastAPI.
- **Alternative considered:** Keep the workflow synchronous or branch on mode
  inside it.
- **Trade-off:** Existing fake/workflow tests needed async conversion. The
  synchronous SQLAlchemy repository remains valid and its short calls run via
  `asyncio.to_thread`, which avoids a database-driver migration in this task.

### GitHub REST before GraphQL

- **Decision:** Use read-only GitHub REST endpoints for PR metadata, reviews,
  branch rules/protection, check runs, and commit statuses.
- **Reason:** REST maps directly to the required evidence, has well-documented
  status semantics, and is straightforward to exercise with `MockTransport`.
- **Alternative considered:** One GraphQL query assembled around nested PR
  review and status data.
- **Trade-off:** REST needs several bounded calls and pagination, increasing
  latency and rate-limit usage. GraphQL could reduce round trips but brings
  query-cost reasoning, cursor handling, and more complex partial-error shapes.

### Normalize and validate at the connector boundary

- **Decision:** Private Pydantic response models validate raw GitHub JSON;
  `HttpGitHubConnector` returns the same frozen internal facts as the fake.
- **Reason:** The workflow and policy remain independent of provider field
  names, nullable values, and endpoint response shapes.
- **Alternative considered:** Pass dictionaries into the workflow or reuse raw
  response models as domain contracts.
- **Trade-off:** The boundary contains explicit mapping code and must be updated
  when GitHub changes a used response field. In return, provider drift fails as
  a sanitized `invalid_response` rather than corrupting a decision.

### Unknown requirements are not invented

- **Decision:** `required_checks_known`, `reviews_known`, and nullable
  `required_approval_count` distinguish known empty requirements from absent
  evidence. GitHub `mergeable=null` maps to indeterminate mergeability.
- **Reason:** A default such as one approval could incorrectly declare a PR
  ready or blocked when repository rules are inaccessible.
- **Alternative considered:** Preserve the former implicit one-approval policy.
- **Trade-off:** Repositories whose rules cannot be read produce `unknown` more
  often, but the result is epistemically honest and a verified blocker still
  takes precedence.

### Bounded pagination and sanitized failures

- **Decision:** List operations request 100 items per page and stop after ten
  pages. HTTP and parsing failures map to a closed GitHub error taxonomy.
- **Reason:** Reviews and checks can span pages, but a request must not loop or
  consume resources without a limit. Provider bodies and exception messages
  are not safe runtime data.
- **Alternative considered:** Fetch only the first page or follow pagination
  until GitHub returns no next page.
- **Trade-off:** More than 1,000 items becomes `invalid_response` rather than an
  incomplete fact set. This is intentionally conservative and can later become
  a configurable, measured limit.

### No fallback and no live Jira claim

- **Decision:** Live GitHub failures remain runtime failures. Live mode injects
  `UnavailableJiraConnector`; mocked HTTP is test infrastructure, not a third
  application mode.
- **Reason:** Falling back would hide outages and mix real and fictional facts.
  A Jira HTTP connector is explicitly outside this milestone.
- **Alternative considered:** Use fake Jira beside live GitHub or silently retry
  against fake GitHub.
- **Trade-off:** Without real Jira evidence, a live run cannot be `ready`; it is
  normally `unknown` unless verified GitHub evidence makes it `blocked`.

## Security and observability

The token is required only in live mode, excluded from settings `repr`, placed
only in the application-scoped client's authorization header, and never copied
into domain facts, errors, logs, spans, or persistence. API base URLs must be
credential-free HTTPS URLs. Connector spans use allowlisted source, operation,
result category, HTTP status class, and page count. Repository identity, PR
content, URLs, raw bodies, and exception messages are excluded.

## Dependency consequence

The connector uses `httpx.AsyncClient`, already installed transitively by the
approved `fastapi[standard]` dependency and already used by FastAPI tests. A
separate direct `httpx` declaration was not added in this bounded change, so
dependency ownership remains indirect. If the FastAPI extra stops providing
it, the backend manifest must add an explicit compatible `httpx` constraint.

## Consequences and limitations

- Fake fixtures remain deterministic and are still the default local mode.
- Automated HTTP tests use `httpx.MockTransport`; they open no real connection.
- Required status is assembled from both check runs and commit statuses.
- The connector does not implement OAuth, GitHub App installation, caching,
  retries, webhooks, Jira HTTP, or cross-provider identity.
- Source provenance is exposed through trace attributes instead of adding a
  run/database schema migration in this milestone.
