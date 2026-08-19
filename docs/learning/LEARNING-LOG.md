# Learning log

This log stores concise, reusable engineering lessons supported by repository
evidence. It is not a conversation transcript, diary, or substitute for an ADR.

## Entry template

### YYYY-MM-DD — Lesson title

- **Concept:** The engineering idea.
- **Important syntax:** Language, framework, or library syntax worth retaining.
- **Implementation location:** Files, functions, tests, or commands providing evidence.
- **Design decision:** The chosen approach and why it fits the concrete task.
- **Invariant or failure behavior:** What later changes must preserve.
- **Misconception corrected:** The prior assumption and more accurate model.
- **Trade-off learned:** The concrete benefit, cost, and relevant conditions.
- **Validation evidence:** Commands or tests demonstrating the behavior.
- **Unresolved question:** A focused question requiring evidence or a decision.

## Repository-supported lessons

### 2026-07-28 — Tool ownership follows language boundaries

- **Concept:** Dependency tooling is separated by ecosystem.
- **Implementation location:** Root `package.json` defines Bun workspaces and
  web scripts; `services/api/pyproject.toml` defines Python requirements for uv.
- **Misconception corrected:** A monorepo need not use one package manager for
  every language.
- **Trade-off learned:** Native tools preserve ecosystem semantics, while
  contributors must run setup in the correct boundary.
- **Unresolved question:** What smallest command surface should coordinate both
  tools when cross-language automation becomes necessary?

### 2026-07-28 — Separate current architecture from plans

- **Concept:** Current components must be distinguishable from intended ones.
- **Implementation location:** `apps/web/src/App.tsx` is a Vite starter and
  `services/api/app/main.py` exposes only `GET /health`.
- **Misconception corrected:** Product direction does not mean runtime,
  persistence, connectors, or security systems exist.
- **Trade-off learned:** Precise current-state docs are less aspirational but
  prevent plans from becoming false operational guarantees.
- **Unresolved question:** Which journey should be the first observable
  frontend-to-API slice?

### 2026-07-30 — Validate connector facts before policy decisions

- **Concept:** A connector boundary should return validated source facts; a
  later policy layer should decide whether those facts mean a pull request is
  merge-ready.
- **Important syntax:** `StrEnum` gives Pydantic fields a closed set of
  string-valued states. `Annotated[int, Field(strict=True, gt=0)]` rejects
  coercion and non-positive PR numbers. `ConfigDict(extra="forbid",
  frozen=True)` rejects unexpected fields and prevents model mutation.
  `MappingProxyType` makes fixture maps read-only, while tuples make nested
  collections immutable. `model_validate(...)` validates fixture variants;
  unlike `model_copy(update=...)`, its updates do not bypass validation.
- **Implementation location:** `services/api/app/connectors/models.py` defines
  the request, GitHub, Jira, and enum contracts. `fixture_catalog.py`,
  `github_fixtures.py`, and `jira_fixtures.py` define eight validated scenarios.
  `fakes.py` performs exact request-key lookup, and `errors.py` defines
  `FixtureNotFoundError`.
- **Design decision:** GitHub and Jira have separate response models and fake
  connectors keyed by the same repository-owner, repository-name, and PR-number
  request. This preserves connector independence without introducing a shared
  policy or HTTP API prematurely.
- **Invariant or failure behavior:** Malformed data raises Pydantic
  `ValidationError`; a valid but unknown identity raises
  `FixtureNotFoundError`. Identical requests return equal frozen snapshots
  without randomness, timestamps, or fallback generation.
- **Misconception corrected:** A fake connector is not safer merely because its
  data is hard-coded. Its fixtures still need boundary validation and immutable
  storage, or tests can silently exercise invalid or mutated states.
- **Trade-off learned:** In-code fixtures are easy to inspect, type, and test
  for this small V1 set. A larger fixture catalog may justify external data
  files, but that would add parsing, discovery, and error-reporting concerns.
- **Validation evidence:** From `services/api`,
  `uv run python -m unittest discover -s tests -v` passed seven tests, and
  `uv run python -m compileall -q app tests` completed successfully.
- **Unresolved question:** When real connectors are introduced, should their
  provider-specific payloads be translated directly into these normalized
  models, or should a separate raw-provider model preserve additional evidence?

### 2026-07-31 — Comments should preserve reasoning, not narrate syntax

- **Concept:** Source documentation is most useful when it explains boundaries,
  invariants, failure translation, and surprising library behavior close to the
  code that depends on them.
- **Important syntax:** A module's first triple-quoted string is its module
  docstring; the same syntax directly inside a class or function documents that
  object. `#` comments are better for a local choice such as `raise ... from
  None`, where suppressing exception chaining would otherwise be non-obvious.
- **Implementation location:** Docstrings and focused inline comments across
  `services/api/app/connectors/*.py` and
  `services/api/tests/unit/test_connector_contracts.py`.
- **Design decision:** Public concepts receive docstrings, while inline comments
  are reserved for choices whose rationale is not encoded by names and types.
  Serialized Pydantic fields were left unchanged so documentation adds no API
  behavior.
- **Invariant or failure behavior:** Documentation must remain consistent with
  strict request validation, frozen contracts, exact fixture lookup, and typed
  `FixtureNotFoundError` translation.
- **Misconception corrected:** More comments do not necessarily create better
  teaching material; comments that repeat assignments increase maintenance cost
  without explaining a reusable idea.
- **Trade-off learned:** Detailed reasoning improves approachability but makes
  source files longer and creates documentation that must evolve with behavior.
- **Validation evidence:** The connector unit suite and Python compilation check
  are rerun after this documentation-only change.
- **Unresolved question:** As real connectors grow, which explanations should
  remain local docstrings and which should move to architecture documentation?

### 2026-07-31 — Destructive commit automation needs a review boundary

> Superseded later on 2026-07-31 by the workspace-preserving Git clean-filter
> workflow below after the required local-source behavior was clarified.

- **Concept:** A source-rewriting pre-commit hook should transform only an
  unambiguous staged scope, validate the result, and stop before creating the
  commit so destructive changes remain reviewable.
- **Important syntax:** Python's `tokenize` module distinguishes real `COMMENT`
  tokens from `#` characters inside strings, while `ast` identifies string
  expressions that are actual module, class, or function docstrings.
  `git diff --cached --name-only -z` safely lists staged paths, and
  `git diff --name-only -z` detects files that also have unstaged changes.
- **Implementation location:** The ignored local files
  `.local-tools/strip_python_comments.py`, its focused unit test, and
  `.githooks/pre-commit`; `.gitignore` keeps this machine-specific workflow out
  of commits.
- **Design decision:** The transformer preserves semantic tooling, security,
  encoding, shebang, and legal comments. Changed source is compiled, written
  atomically, staged, tested, and then the commit is intentionally aborted for
  review rather than silently continuing.
- **Invariant or failure behavior:** Partially staged Python files are never
  rewritten. A parsing, compilation, write, staging, or test failure prevents
  the commit. Re-running the transformer on already stripped code is a no-op.
- **Misconception corrected:** A pre-commit hook that automatically edits and
  completes a commit is not necessarily convenient; it can hide destructive
  changes and accidentally stage unrelated working-tree content.
- **Trade-off learned:** Ignoring the hook and transformer satisfies a local-only
  workflow but means other clones do not inherit or enforce comment removal.
- **Validation evidence:** Five transformer tests, seven connector tests, Python
  compilation, Git ignore matching, hook shell syntax, and its no-change path
  passed. The checkout uses `core.hooksPath=.githooks`.
- **Unresolved question:** If this workflow later becomes team policy, should
  the hook become tracked repository tooling or a server-side CI check?

### 2026-07-31 — Git clean filters can separate workspace and stored content

- **Concept:** A Git clean filter transforms bytes while Git creates an index
  blob, allowing the commented working file and comment-free committed file to
  differ without rewriting the workspace.
- **Important syntax:** `*.py filter=comment-strip` assigns a Git attribute.
  `filter.comment-strip.clean` defines the stdin-to-stdout transformer, while
  `filter.comment-strip.required=true` makes Git fail instead of silently
  storing unfiltered content when the transformer is unavailable.
- **Implementation location:** The ignored local files
  `.local-tools/gitattributes`, `strip_python_comments.py`, and its unit test;
  local Git configuration points `core.attributesFile` at the ignored attribute
  file. The earlier `.githooks/pre-commit` file and `core.hooksPath` setting were
  removed.
- **Design decision:** The transformer is now a pure stream operation: it reads
  one Python file from standard input and writes stripped bytes to standard
  output. It performs no filesystem or index mutation.
- **Invariant or failure behavior:** Git receives compiled, comment-free Python,
  while the workspace bytes remain unchanged. Semantic directives remain, and
  parsing or compilation failure blocks Git from accepting the filtered blob.
- **Misconception corrected:** A pre-commit rewrite cannot provide a temporary
  Git-only representation because editing and restaging necessarily changes the
  workspace. Git's clean-filter boundary is designed for this separation.
- **Trade-off learned:** Commented source remains convenient locally, but the
  comments are not backed up in Git, clones receive only comment-free source,
  and this ignored local filter is not automatically configured in another
  checkout.
- **Validation evidence:** Unit tests cover parsing and preservation. Filtered
  and unfiltered Git hashes differ while the workspace SHA-256 remains unchanged;
  existing connector tests and compilation also pass.
- **Unresolved question:** Should future TypeScript support use a corresponding
  syntax-aware clean filter, or should comment-free storage remain Python-only?

### 2026-07-31 — Form drafts and validated requests are different types

- **Concept:** Browser input state should model what a user can temporarily
  type, while the domain request should model only values safe to serialize.
- **Important syntax:** A discriminated union using `ok: true | false` lets
  TypeScript narrow a validation result to either `request` or `errors`.
  `Partial<Record<keyof ConnectorRequestDraft, string>>` derives error keys
  directly from editable fields, avoiding a second manually synchronized list.
- **Implementation location:** `apps/web/src/features/inspection/types.ts` and
  `requestValidation.ts` define the draft, request, errors, and conversion;
  `components/RequestForm.tsx` renders controlled inputs and accessible errors.
- **Design decision:** `pr_number` remains a string in editable state and becomes
  a number only after digit-only and safe-integer validation. Final JSON keys use
  the backend's snake_case names so no mapping layer can drift.
- **Invariant or failure behavior:** Empty owner/repository values, zero,
  negatives, decimals, exponent notation, and unsafe integers never produce a
  `ConnectorRequest`. Submitting valid input only previews data and performs no
  network request.
- **Misconception corrected:** Using `type="number"` does not automatically make
  React state a valid backend number; DOM values are strings and number inputs
  can still represent intermediate invalid states.
- **Trade-off learned:** Frontend validation gives immediate feedback but cannot
  replace Pydantic validation at the future HTTP boundary.
- **Validation evidence:** TypeScript/Vite build and Oxlint are run after the UI
  implementation.
- **Unresolved question:** When an API route exists, should submission remain a
  single request or expose GitHub and Jira connector progress independently?

### 2026-07-31 — Versioned HTTP contracts need validation on both sides

- **Concept:** Static TypeScript types do not validate JSON received at runtime;
  Pydantic protects the server boundary, while browser type guards protect the
  rendering boundary from API drift or malformed intermediaries.
- **Important syntax:** FastAPI `response_model` documents and serializes typed
  responses, `responses={404: {"model": ApiError}}` documents an expected
  failure, and an exception handler translates a domain lookup error into a
  stable top-level HTTP body. TypeScript `unknown` plus type predicates such as
  `value is PullRequestInspection` require proof before rendering.
- **Implementation location:** `services/api/app/api/v1` owns HTTP routes and
  error models; `app/inspection` owns orchestration; `app/main.py` registers
  routing and error translation. Frontend `features/inspection/api.ts` owns
  fetch calls, `responseValidation.ts` owns runtime parsing, and
  `ConnectorInspectionPage.tsx` owns UI state transitions.

- **Design decision:** A demo-prefixed catalog remains separate from the stable
  inspection POST, and Vite proxies relative `/v1` browser URLs locally. This
  prevents frontend fixture duplication and avoids broad CORS configuration.
- **Invariant or failure behavior:** The backend is the only scenario source;
  invalid requests return `422`, unknown fixtures return typed `404`, malformed
  responses never render, and inspection data contains no policy conclusion.
- **Misconception corrected:** Matching TypeScript interfaces and Pydantic
  classes does not guarantee runtime compatibility because TypeScript types are
  erased and network payloads remain untrusted values.
- **Trade-off learned:** Handwritten browser guards add code and mirror response
  fields, but avoid a new schema/code-generation dependency in this V1 slice.
- **Validation evidence:** Five focused API tests and seven connector tests pass;
  frontend parser assertions, Oxlint, TypeScript compilation, and Vite build
  pass. TestClient emits a dependency deprecation warning without test failure.
- **Unresolved question:** When the API surface grows, should OpenAPI-generated
  types and runtime schemas replace handwritten frontend contracts?

### 2026-08-01 — Modularization should follow questions, not file size

- **Concept:** A useful module boundary lets a reader open one file to answer
  one concrete question. Splitting solely because a file is long can increase
  navigation without improving understanding.
- **Important syntax:** Python modules are imported `.py` files, packages are
  directories containing `__init__.py`, and leading underscores communicate
  private conventions. React components are ordinary functions whose typed
  props define their inputs; custom feature modules can separate data, effects,
  validation, and rendering without a framework.
- **Implementation location:** Python provider fixtures now live in
  `fixture_catalog.py`, `github_fixtures.py`, and `jira_fixtures.py`; plain
  application functions live in `inspection/service.py`. The frontend feature
  is organized under `apps/web/src/features/inspection` by types, validation,
  transport, coordination, and presentation.
- **Design decision:** Routes remain HTTP-only and delegate to two service
  functions instead of introducing a dependency-injection framework. `App.tsx`
  delegates to one feature page, while form and response components remain
  stateless except for DOM events.
- **Invariant or failure behavior:** Endpoint paths, JSON contracts, all eight
  fixture values, error statuses, runtime response validation, and visible UI
  behavior remain unchanged by the module moves.
- **Misconception corrected:** More abstraction is not always more modular. A
  class, interface, or framework is unnecessary when two named functions express
  the complete application use case clearly.
- **Trade-off learned:** The refactor adds files and import statements, but each
  file is shorter, provider ownership is explicit, and beginners can follow the
  request flow in one direction.
- **Validation evidence:** Twelve backend tests and compilation pass after the
  Python split; frontend TypeScript build, Oxlint, and boundary assertions pass
  after the component and transport split.
- **Unresolved question:** At what feature count should shared frontend runtime
  validation helpers move out of the inspection feature?

### 2026-08-02 — Deterministic policy separates facts from conclusions

- **Concept:** Connector facts and policy conclusions have different ownership.
  A pure policy function can turn immutable source facts into a reproducible
  decision without knowing how those facts were retrieved.
- **Important syntax:** A union such as `GitHubPullRequest | None` makes
  unavailable evidence explicit in the function type. `StrEnum` provides stable
  machine-readable decision, reason, action, and source values. Frozen Pydantic
  models and tuples make the returned result immutable by contract.
- **Implementation location:** `services/api/app/policy/models.py` defines typed
  results and `evaluator.py` implements the rules. The focused behavior tests
  are in `services/api/tests/unit/test_merge_readiness_policy.py`.
- **Design decision:** The evaluator uses direct ordered checks instead of a
  generic rule engine. It collects every verified blocker and every missing
  fact before applying the precedence `blocked`, then `unknown`, then `ready`.
  Findings point to typed evidence references rather than relying only on prose.
- **Invariant or failure behavior:** Missing or indeterminate evidence never
  becomes a blocker. A verified blocker still wins when other evidence is
  unavailable, and no early return hides simultaneous blockers. Jira facts are
  used only when their issue key matches the key linked by GitHub.
- **Trade-off learned:** A fixed requirement of one approval and direct checks
  are easy to understand and deterministic for V1, but they do not support
  repository-specific policy configuration. `None` expresses availability but
  does not explain whether a connector timed out, lacked permission, or was
  rate-limited.
- **Validation evidence:**
  `uv run python -m unittest tests.unit.test_merge_readiness_policy -v` passed
  10 policy tests; `uv run python -m unittest discover -s tests -v` passed all
  22 backend tests with the existing `TestClient` deprecation warning; and
  `uv run python -m compileall -q app tests` passed.
- **Unresolved question:** When real connector failures arrive, should `None`
  become a typed availability object that distinguishes retryable failures from
  permission or configuration failures?

### 2026-08-02 — Orchestration makes a pure policy usable without moving its rules

- **Concept:** A pure policy becomes an application workflow only when an
  orchestration boundary retrieves facts, handles availability, calls the
  policy, and returns both conclusions and supporting evidence. The route and
  frontend should transport that result rather than reimplement it.
- **Important syntax:** FastAPI `Depends` supplies default fake connectors while
  `app.dependency_overrides` supplies deterministic unavailable test doubles.
  Python `Protocol` describes the small connector method each service needs.
  In TypeScript, network JSON remains `unknown` until runtime guards prove the
  nested `policy_result` and optional connector facts.
- **Implementation location:** `app.inspection.service.analyze_pull_request_merge_readiness`
  coordinates connectors and `evaluate_merge_readiness`; the route is in
  `app/api/v1/connector_router.py`. Frontend `api.ts` calls the new endpoint,
  `responseValidation.ts` validates it, and `MergeReadinessPanel.tsx` renders it.
- **Design decision:** A dedicated `/v1/pull-request-merge-readiness` endpoint
  preserves ADR-001’s facts-only inspection contract. The response nests the
  complete decision under `policy_result` and keeps nullable raw facts beside
  it for evidence and debugging.
- **Invariant or failure behavior:** Only `ConnectorUnavailableError` becomes
  missing evidence. Fixture-not-found remains `404`, request validation remains
  `422`, verified blockers beat missing evidence, and the frontend displays
  `policy_result.decision` without deriving it from blocker counts.
- **Trade-off learned:** An additive endpoint and response wrapper add types and
  one URL, but avoid a breaking response change. FastAPI dependency providers
  add a small amount of wiring while enabling HTTP tests for partial failures
  that predefined fixtures do not produce.
- **Validation evidence:** `uv run python -m unittest discover -s tests -v`
  passed 29 backend tests with the existing `TestClient` warning;
  `uv run python -m compileall -q app tests` passed; `bun run test:web` passed
  7 frontend tests; and `bun run build:web` plus `bun run lint:web` passed.
- **Unresolved question:** When connector failure reasons become user-visible,
  should the HTTP result expose retryability and permission details separately
  from policy missing-information messages?

### 2026-08-02 — Runtime status and policy decision describe different failures

- **Concept:** A workflow run answers whether execution succeeded, while a
  policy result answers whether the known facts permit merging. Failed CI is a
  successful execution with `decision=blocked`; an unexpected connector or
  policy exception is a failed execution with no policy result.
- **Important syntax:** Frozen Pydantic snapshots plus explicit transition
  functions prevent terminal state reversal. `Protocol` defines the small
  `RunRepository` storage boundary, `uuid4()` creates unique operational IDs,
  UTC `datetime` values record wall-clock events, and `perf_counter_ns()`
  measures durations without depending on wall-clock adjustments.
- **Implementation location:** `app/runtime/models.py` defines run, step, and
  error contracts; `runtime/state.py` enforces transitions;
  `runtime/repository.py` isolates storage; and
  `workflows/merge_readiness.py` records the connector and policy sequence. The
  route delegates through `get_merge_readiness_workflow`.
- **Design decision:** Synchronous execution failures return HTTP `500` with the
  complete typed failed run. Completed runs return `200`. This preserves both
  truthful HTTP semantics and the run ID, timestamps, step history, and safe
  failure category.
- **Invariant or failure behavior:** Completed runs contain `result` and no
  runtime error. Failed runs contain `result=null` and a fixed sanitized error.
  Connector unavailability remains missing evidence rather than a system
  failure, terminal states cannot return to running, and identical facts still
  produce equal policy results even though run metadata differs.
- **Trade-off learned:** Request-local in-memory storage proves the repository
  boundary and snapshot recording without database design, but runs cannot be
  retrieved after the request and disappear on process restart. Sequential
  steps simplify ordering but would include full connector latency later.
- **Validation evidence:** `uv run python -m unittest discover -s tests -v`
  passed 38 backend tests with the existing `TestClient` warning;
  `uv run python -m compileall -q app tests` passed; `bun run test:web` passed
  7 frontend tests; and `bun run build:web` plus `bun run lint:web` passed.
- **Unresolved question:** Should the first persistence task store every runtime
  snapshot as history, or store only the latest run plus separate step events?

### 2026-08-03 — Durability is a commit guarantee, not an in-memory result

- **Concept:** A workflow result becomes durable only after PostgreSQL confirms
  the transaction. Computing a policy result in memory is insufficient for an
  HTTP `200`; a terminal persistence failure must return `503` without claiming
  the run completed or failed durably.
- **Important syntax:** SQLAlchemy's `sessionmaker.begin()` scopes one session,
  transaction, commit, rollback, and close around a repository save. PostgreSQL
  `JSONB` stores typed snapshots while `UUID`, `TIMESTAMPTZ`, `TEXT`, and
  `INTEGER` columns keep identity, lifecycle, timing, and ordering queryable.
  Alembic's `upgrade()` and `downgrade()` functions version schema changes
  independently of application startup.
- **Implementation location:** `app/database/models.py` defines relational
  constraints; `postgres_run_repository.py` conditionally stores and rebuilds
  Pydantic runs; `migrations/versions/20260803_0001_create_runtime_tables.py`
  creates the schema; and `connector_router.py` exposes `GET /v1/runs/{run_id}`.
- **Design decision:** Neon hosts ordinary PostgreSQL, while provider-neutral
  SQLAlchemy 2.x and psycopg 3 own application access. Application traffic uses
  a pooled URL, Alembic requires a separate direct URL, and production has no
  memory fallback. Terminal step and run state share one repository commit.
- **Invariant or failure behavior:** No transaction remains open during GitHub,
  Jira, or policy work. HTTP `200` or the typed runtime `500` is returned only
  after the corresponding terminal row commits. Persistence uncertainty uses a
  fixed sanitized `503`; stored JSON is revalidated before retrieval.
- **Trade-off learned:** JSONB avoids normalizing every provider fact and keeps
  the current typed response reconstructible, but PostgreSQL enforces only that
  each value is an object; Pydantic enforces its nested structure. Conditional
  status updates fit one V1 owner per run, while future workers will likely need
  an optimistic version column.
- **Validation evidence:** `uv run python -m unittest discover -s tests -v`
  discovered 54 tests: 50 passed and four PostgreSQL tests skipped explicitly
  because `TEST_DATABASE_URL` was absent. Python compilation passed, Alembic
  reported one head, and offline migration SQL rendered successfully without a
  database connection.
- **Unresolved question:** When recovery is introduced, should a stranded
  running step be marked failed by an operator action or claimed by a worker
  through an optimistic version check?

### 2026-08-03 — JSON `null` and SQL `NULL` are different values

- **Concept:** An optional JSONB column has two possible null representations.
  SQL `NULL` means no database value exists, while JSON `null` is a present JSON
  scalar. A constraint that permits SQL `NULL` or a JSON object rejects JSON
  `null`.
- **Important syntax:** `JSONB(none_as_null=True)` tells SQLAlchemy to bind
  Python `None` as SQL `NULL`. Without this option, SQLAlchemy's JSON type uses
  JSON `null`, even though both values appear as `None` when first reading the
  Python model.
- **Implementation location:** Optional run and step snapshot mappings in
  `app/database/models.py` now use `none_as_null=True`.
  `tests/unit/test_database_models.py` checks the PostgreSQL bind behavior for
  GitHub facts, Jira facts, policy result, and runtime errors.
- **Design decision:** Fix the mapping rather than weakening the database
  constraints. The constraints still reject arrays, strings, numbers, and JSON
  `null`, so a present snapshot must remain an object.
- **Invariant or failure behavior:** Missing facts, result, and errors persist as
  SQL `NULL`; present typed snapshots persist as JSON objects. This allows a
  pending run to be inserted before connector evidence exists.
- **Trade-off learned:** The mapping flag is small and preserves strict storage
  validation, but its behavior is PostgreSQL-dialect-specific and therefore
  needs a focused mapping test in addition to Pydantic tests.
- **Validation evidence:** The focused database-model unit test passed. Full
  backend discovery ran 55 tests: 51 passed and four isolated PostgreSQL tests
  skipped because `TEST_DATABASE_URL` was not configured. A failed-CI fixture
  executed against the configured application database and durably returned
  `status=completed`, `decision=blocked`, and three recorded steps.
- **Unresolved question:** If the persistence model gains more optional JSONB
  columns, should a shared annotated SQLAlchemy type enforce this setting in
  one place, or is explicit per-column configuration clearer at the current
  size?

### 2026-08-03 — Correlation identifiers make durable runs usable

- **Concept:** A durable run is easier to inspect when its identifier appears in
  the server's normal operational output. The ID connects one POST execution to
  the stored resource available through `GET /v1/runs/{run_id}`.
- **Important syntax:** Python logging keeps the message template separate from
  values: `logger.info("...%s", value)`. This defers formatting until the logger
  needs the record and avoids manually constructing log strings.
- **Implementation location:** `analyze_pull_request()` in
  `app/api/v1/connector_router.py` logs the terminal `run_id`, runtime status,
  and policy decision through Uvicorn's configured logger. Its HTTP integration
  test captures and verifies the exact safe fields.
- **Design decision:** Log once after workflow execution returns, when the route
  has a committed terminal run. This avoids noisy logs for every immutable
  checkpoint and keeps policy logic outside the HTTP layer.
- **Invariant or failure behavior:** The log may contain operational identifiers
  and enums, but never repository input, connector evidence, exception text,
  secrets, or stack traces.
- **Trade-off learned:** Reusing `uvicorn.error` makes the line immediately
  visible with the current server configuration, but couples this small
  presentation concern to Uvicorn. A later structured-logging task should
  replace it if the application runs under multiple server implementations.
- **Validation evidence:** The focused API test passed and proved that the log's
  run ID equals the ID returned by the typed HTTP response.
- **Unresolved question:** Should future request-level correlation use the run
  ID directly, or introduce a separate request ID for calls that fail before a
  durable run is created?

### 2026-08-04 — Observability must describe committed reality

- **Concept:** A trace connects related work through parent-child spans, while
  counters count occurrences and histograms record distributions such as
  latency. Traces explain one run; metrics summarize many runs; a terminal JSON
  event gives a searchable, correlated operational fact.
- **Important syntax:** `start_as_current_span(..., record_exception=False,
  set_status_on_exception=False)` prevents an escaping Python exception from
  automatically adding its message and stack to a span. `ContextVar` carries a
  closed persistence checkpoint through the repository decorator without
  changing `RunRepository.save(run)`. Counters use `add()`; histograms use
  `record()` with seconds as the unit.
- **Implementation location:** `app/observability/runtime_telemetry.py` owns the
  five instruments and domain spans; `observed_run_repository.py` decorates any
  repository; `setup.py` owns providers, OTLP exporters, FastAPI
  instrumentation, and shutdown; `structured_logging.py` emits safe JSON.
- **Design decision:** OpenTelemetry keeps instrumentation provider-neutral,
  while Grafana Cloud is only the current OTLP HTTP/protobuf destination.
  Terminal metrics and logs run after the terminal repository save, so they
  report a committed fact instead of a computed but possibly uncommitted one.
- **Invariant or failure behavior:** `ready`, `blocked`, and `unknown` are
  successful completed traces. System failures use a closed category. If the
  terminal commit fails, no terminal run metric or success event is emitted;
  exporter failure never changes the runtime, persistence, or HTTP result.
- **Trade-off learned:** Batch export keeps network latency out of requests and
  supports a hosted backend, but bounded in-process queues can lose recent
  telemetry on abrupt shutdown. Exact metric-label allowlists prevent
  high-cardinality IDs and input values, at the cost of deliberately limited
  slice-and-dice dimensions.
- **Validation evidence:** `uv run python -m compileall -q app tests` passed;
  full unittest discovery ran 68 tests with 64 passing and four PostgreSQL tests
  skipped because `TEST_DATABASE_URL` was absent. Seven frontend tests, the
  TypeScript/Vite build, and Oxlint also passed.
- **Unresolved question:** Once production traffic exists, which service-level
  objectives should determine dashboard panels and alert thresholds without
  turning every available measurement into an alert?

### 2026-08-04 — Normalize external APIs behind an asynchronous protocol

- **Concept:** Dependency inversion lets the workflow depend on the small
  `GitHubConnector` behavior it needs instead of either fixture lookup or HTTP.
  Dependency injection then selects `FakeGitHubConnector` or
  `HttpGitHubConnector` at FastAPI assembly. A mocked HTTP transport is not a
  fake connector: it replaces network delivery in tests while still exercising
  real request, pagination, validation, error, and normalization code.
- **Important syntax:** `Protocol` describes structural behavior without a base
  class; `async def` plus `await` lets GitHub I/O yield the event loop;
  `asyncio.to_thread()` keeps the approved synchronous SQLAlchemy repository
  calls off that loop. Private Pydantic response models use
  `model_validate(payload)` to reject missing or malformed provider fields.
  Frozen dataclass/settings fields use `field(repr=False)` so a token cannot
  accidentally appear in a settings representation.
- **Implementation locations:** `app/connectors/protocols.py` owns the shared
  contract; `github_http_models.py` validates raw REST shapes;
  `github_http.py` normalizes evidence; `factory.py`, `config.py`, and
  `main.py` select and own the application-scoped client; the workflow awaits
  the protocol. `test_github_http_connector.py` uses `httpx.MockTransport` and
  `test_github_connector_factory.py` proves the two actual runtime modes.
- **Design decision:** REST was chosen before GraphQL because the required PR,
  review, rule, and status evidence maps to documented endpoints and realistic
  minimal response fixtures. Pages are limited to ten. Live failures never
  fall back to fake facts, and absent branch-rule evidence never invents a
  default approval count or required-check set.
- **Invariant or failure behavior:** External JSON never leaves the connector
  boundary. `mergeable=null`, inaccessible requirements, and inaccessible
  reviews become missing evidence; any independently verified blocker still
  takes precedence. Provider errors enter a sanitized closed taxonomy, while
  tokens, headers, raw bodies, URLs, repository content, and exception text are
  excluded from runtime errors and telemetry.
- **Trade-off:** Several REST calls increase latency and rate-limit use versus a
  tailored GraphQL query. The conservative pagination bound can reject very
  large histories instead of returning incomplete evidence. Live mode also
  cannot return `ready` until a real Jira connector exists, because using fake
  Jira beside live GitHub would mix factual and fictional evidence.
- **Validation evidence:** Focused connector/factory discovery ran 21 tests.
  Full backend discovery ran 91 tests successfully; four PostgreSQL integration
  tests skipped because `TEST_DATABASE_URL` was absent. Seven frontend tests,
  the TypeScript/Vite production build, and Oxlint passed. Automated GitHub
  tests inject `MockTransport` and therefore open no real GitHub connection.
- **Unresolved question:** Should `httpx` become an explicit direct dependency
  rather than remain transitively provided by `fastapi[standard]`? Direct
  ownership is clearer, but adding it requires a separately approved manifest
  and lockfile decision.

### 2026-08-04 — Normalize custom Jira workflows through status categories

- **Concept:** External display names are not always business semantics. Jira
  administrators can create arbitrary status names, while the stable category
  keys `new`, `indeterminate`, and `done` provide the broad lifecycle fact this
  policy needs. The connector reports normalized evidence; the pure policy
  remains the only place that decides readiness.
- **Important syntax:** An async `Protocol` lets fake and HTTP Jira satisfy the
  same key-based operation without inheritance. `httpx.BasicAuth(email, token)`
  constructs the secret header without putting credentials in a URL.
  `httpx.Timeout(connect=..., read=..., write=..., pool=...)` makes each wait
  boundary explicit. Pydantic `Literal` restricts raw status-category keys, and
  optional model defaults keep older JSONB snapshots reconstructible.
- **Implementation locations:** `app/connectors/jira_http_models.py` validates
  the minimal REST v3 response; `jira_http.py` handles key validation, HTTP,
  error mapping, and normalization; `config.py`, `factory.py`, and `main.py`
  select and own the client; `merge_readiness.py` awaits the key-based protocol;
  `evaluator.py` handles unknown blocker evidence deterministically.
- **Design decision:** Jira and GitHub source modes are independent. The live
  Jira request fetches only status, assignee, and resolution and needs no
  pagination. Email/API-token Basic authentication is accepted only for this
  single-user V1; OAuth or an Atlassian app is deferred.
- **Invariant or failure behavior:** A malformed Jira key causes no HTTP call.
  A live failure never returns fake facts. Status names never determine
  completion. Because standard Jira has no universal blocker field, live facts
  say `blocker_state=unknown`; a verified incomplete status still makes the
  result blocked, while a done issue with unknown blocker evidence is unknown.
  Secrets, provider bodies, issue identity, account data, and URLs never enter
  runtime errors or telemetry.
- **Trade-off:** Restricting base URLs to HTTPS `*.atlassian.net` reduces SSRF
  surface but excludes custom-domain aliases. Avoiding site-specific custom
  fields keeps the connector portable but prevents a fully ready live result
  until blocker evidence is configured. Source provenance stays in spans, so
  this task needs no public response or PostgreSQL migration.
- **Validation evidence:** The Jira-focused suite ran 18 tests. Backend
  discovery ran 111 tests successfully, with four PostgreSQL tests skipped
  because `TEST_DATABASE_URL` was absent. Seven frontend tests, the
  TypeScript/Vite build, Oxlint, Python compileall, and `git diff --check`
  passed. Every Jira connector test client that sends requests uses
  `httpx.MockTransport`; no Atlassian or GitHub request was made.
- **Unresolved question:** Which explicit Jira field or link convention should
  become the repository's site-specific blocker source before live Jira can
  prove `not_blocked` rather than `unknown`?

### 2026-08-04 — Make connector selection visible without logging credentials

- **Concept:** Configuration provenance is operational evidence. Logging the
  selected connector implementations once at application startup answers
  whether GitHub and Jira are using live HTTP or deterministic fixtures without
  putting that provenance into every request, database row, or public response.
- **Important syntax:** FastAPI's async lifespan runs when a server process
  starts and stops, unlike module-level code that also runs during imports.
  Passing `ConnectorSource` enums to `StructuredEventLogger.emit()` produces
  stable `live` or `fake` JSON strings through the logger's enum conversion.
- **Implementation locations:** `app/main.py` emits
  `runtime.connector_sources.selected` when lifespan startup begins;
  `app/observability/structured_logging.py` explicitly allows only the two new
  source fields; `test_application_startup_logging.py` exercises the real
  lifespan with live GitHub and fake Jira settings.
- **Design decision:** Emit one startup event rather than one event per request.
  This avoids noisy duplicate logs while operation spans continue to prove the
  source used by individual connector calls. The event occurs before database
  readiness, so connector selection remains visible when database startup
  subsequently fails.
- **Invariant or failure behavior:** The event contains only
  `github_source` and `jira_source`; it excludes tokens, emails, URLs, request
  identity, provider payloads, and raw errors. Structured logging remains best
  effort and cannot change application or workflow behavior.
- **Trade-off:** A development reload emits the event again because it creates
  a new server process. The source pair is not queryable through the run API or
  durable database, avoiding a schema/API migration at the cost of relying on
  server logs for this application-level configuration fact.
- **Validation evidence:** The focused startup test passed. Full backend
  discovery ran 112 tests successfully, with four PostgreSQL integration tests
  skipped because `TEST_DATABASE_URL` was absent. Python `compileall` passed.
- **Unresolved question:** If connector mode later becomes tenant-specific,
  should bounded source provenance move from application startup into each run
  record without exposing tenant-controlled identifiers as metric labels?

### 2026-08-05 — Readable orchestration exposes sequence without removing boundaries

- **Concept:** A top-level workflow should name business operations in their
  execution order, while step methods own the persistence, timing, telemetry,
  and sanitized failure behavior required by each operation. Readability comes
  from separating levels of detail, not from deleting resource and safety
  boundaries.
- **Important syntax:** FastAPI's `@asynccontextmanager` runs code before
  `yield` at startup and the `finally` block at shutdown. Explicit `if value is
  not None` branches distinguish injected dependencies from environment
  defaults. Frozen Pydantic snapshots are updated by dumping, changing, and
  revalidating a new model. `asyncio.to_thread()` keeps synchronous SQLAlchemy
  saves outside the event-loop thread.
- **Implementation locations:** `app/main.py:create_app` shows assembly,
  startup, and shutdown phases; `connector_router.py:analyze_pull_request`
  shows HTTP input, workflow call, and output; and
  `workflows/merge_readiness.py:_execute_workflow` shows GitHub, Jira, and
  policy order. `runtime/state.py` has type-specific immutable replacements,
  and `database/postgres_run_repository.py:_read_run` explicitly reconstructs
  typed storage values.
- **Design decision:** Keep the workflow service class because it shares
  connectors, repository, clocks, and telemetry across several operations.
  Extract only complete workflow steps and the repeated atomic failure
  checkpoint; avoid a generic executor, decorator, or new result framework.
- **Invariant or failure behavior:** Three steps retain their existing names and
  order. Connector and policy calls run outside database transactions. A failed
  step and run commit together, and the completed policy step and result commit
  together, before terminal telemetry and HTTP output. Public routes, JSON,
  status codes, fake/live selection, and sanitized errors remain unchanged.
- **Misconception corrected:** Fewer functions are not automatically easier to
  read. One long workflow path mixed business sequence with several necessary
  detail levels; named step methods make the sequence traceable while retaining
  the same class and file.
- **Trade-off learned:** The refactor adds a few explicit branches and helper
  calls, so total line count is not the optimization target. In exchange, each
  function has one reading level and can be debugged at a meaningful workflow
  boundary without introducing more modules or production dependencies.
- **Validation evidence:** Pre-refactor backend discovery ran 112 tests with
  four guarded PostgreSQL skips. Focused startup/API, workflow/observability,
  and runtime/policy tests passed after their respective changes. Final
  compile, complete discovery, and diff checks are recorded in the execution
  plan and task response.
- **Unresolved question:** If a fourth workflow step is added, does the explicit
  step-method pattern remain clearer, or has enough real duplication appeared
  to justify a small typed step result?

### 2026-08-05 — Generated Git source should not add empty statements

- **Concept:** A Git clean filter is a source transformation boundary. Its
  generated representation must stay valid and readable without changing the
  commented working-tree source used for learning.
- **Important syntax:** Python needs `pass` only when a suite would otherwise be
  empty. Removing a docstring from a function that still has executable
  statements does not require a replacement statement.
- **Implementation location:** The local `comment-strip` filter now preserves
  `pass` only for genuinely empty suites. The committed cleanup touches the
  previously refactored API workflow files and is validated through full
  backend discovery, `compileall`, and `git diff --check`.
- **Design decision:** Correct the local Git transformation instead of deleting
  useful workspace docstrings. Also use `terminal_run` at the route boundary
  because both completed and failed runs are terminal responses.
- **Invariant or failure behavior:** Workspace comments remain available;
  committed Python compiles; public API, state, persistence, policy, connector,
  and telemetry behavior remains unchanged.
- **Trade-off learned:** The index representation no longer preserves exact
  blank-line positions for removed teaching text, but reviewers receive cleaner
  source without meaningless statements or excessive gaps.
- **Validation evidence:** Recorded in the cleanup commit and task response.
- **Unresolved question:** None for this mechanical cleanup.

### 2026-08-09 — Separate unknown optional evidence from unknown required evidence

- **Concept:** A three-valued provider fact can remain honestly `unknown`
  without making the whole decision unknown when that fact is optional. This
  differs from required evidence such as mergeability or required-check rules,
  whose absence still prevents a proven ready result.
- **Important syntax:** The evaluator needs only the positive
  `if jira.blocker_state is BlockerState.BLOCKED` branch. Omitting an
  `UNKNOWN` decision branch does not relabel the enum; the earlier
  `_record_evidence(...)` call still serializes its exact `"unknown"` value.
- **Implementation locations:** `app/policy/evaluator.py` removes the promotion
  of optional blocker metadata into missing information.
  `test_merge_readiness_policy.py` covers all three blocker states and confirms
  required GitHub uncertainty still produces `unknown`. ADR-008 records why
  this narrowly supersedes ADR-007's earlier policy consequence.
- **Design decision:** Jira blocker metadata is optional supplementary evidence
  in V1 because standard Jira has no portable blocker field. An explicit
  `BLOCKED` fact remains authoritative, but `UNKNOWN` adds no retry action or
  missing-information finding.
- **Invariant or failure behavior:** Decision precedence remains verified
  blocker, then missing required evidence, then ready. `UNKNOWN` is never
  rewritten as `NOT_BLOCKED`, and connector facts, API shapes, persistence,
  frontend rendering, and telemetry remain unchanged.
- **Trade-off:** Standard live Jira can now participate in a useful ready
  decision without tenant-specific setup, but V1 cannot detect blockers stored
  only in custom fields or local Jira conventions.
- **Validation evidence:** The focused policy suite passed 16 tests. Complete
  backend discovery passed 114 tests with four PostgreSQL integration tests
  skipped because `TEST_DATABASE_URL` was absent. `python -m compileall -q app
  tests` passed. No automated test contacted an external provider.
- **Unresolved question:** If tenant-specific blocker mappings are introduced,
  how will their configuration be validated, versioned, authorized, and
  audited before they can strengthen the normalized blocker fact?

### 2026-08-09 — Put probabilistic explanation behind a deterministic boundary

- **Concept:** An LLM harness owns minimized input, provider substitution,
  structured-output validation, sanitized failures, and safe telemetry. It does
  not own the deterministic business decision it explains.
- **Important syntax:** A Python `Protocol` defines the async
  `generate_structured(...)` operation without requiring inheritance.
  `Annotated[str, StringConstraints(...)]` bounds explanation text, while
  frozen Pydantic models reject extra fields. Application injection uses an
  optional protocol argument and stores the assembled service in FastAPI state.
- **Implementation locations:** `app/explanations` contains the models, client
  contract, fake, error, and service boundaries. `app/main.py` selects the fake
  or injected client. `observability/contracts.py` and
  `runtime_telemetry.py` add allowlisted model-call spans and metrics.
  `test_merge_readiness_explanations.py` proves the security and failure rules.
- **Decision:** Keep explanation generation internal and independent of
  `MergeReadinessWorkflowService` until a deterministic semantic validator
  exists.
- **Reason:** Pydantic proves output shape and the service proves decision
  equality, but neither proves that arbitrary explanation sentences are
  supported by policy evidence.
- **Alternative considered:** Add the model call as a runtime step now or choose
  a real provider SDK first.
- **Tradeoff:** The trust boundary and telemetry are testable without network,
  credentials, cost, or vendor coupling, but no user can receive an LLM
  explanation yet.
- **Invariant or failure behavior:** Only decision and stable reason/action
  codes reach the client. A provider exception, malformed shape, or changed
  decision becomes a typed sanitized error and cannot modify the immutable
  policy result or persisted run. Prompts, outputs, evidence values, identities,
  credentials, and raw errors never enter logs, spans, or metric labels.
- **Validation evidence:** Eight focused explanation tests and thirteen focused
  observability regressions passed. Complete backend discovery ran 122 tests
  successfully, with four PostgreSQL tests skipped because `TEST_DATABASE_URL`
  was absent. `python -m compileall -q app tests` and `git diff --check` passed.
  No backend formatter, linter, or static type checker is configured, and no
  automated test contacted an external model service.
- **Unresolved question:** What deterministic rules should the next validator
  use to prove each reason and recommended action is supported by the supplied
  policy codes before API exposure?

### 2026-08-09 — Validate generated wording before crossing the API boundary

- **Concept:** Structured-output validation has two layers. Pydantic proves the
  JSON shape, while a deterministic semantic validator proves that every word,
  reason, action, and ordering matches backend-owned policy templates.
- **Important syntax:** Python dictionary lookups keyed by `StrEnum` values turn
  stable reason/action codes into exact text. Pydantic model equality compares
  the complete immutable explanation. In TypeScript, runtime type guards narrow
  network `unknown`, and the parser additionally checks
  `explanation.decision === result.decision` before returning a typed value.
- **Implementation locations:** `app/explanations/templates.py` owns the closed
  wording maps; `validator.py` rejects any complete-object mismatch; `service.py`
  converts rejection into a sanitized typed failure. `app/api/v1/models.py` and
  `connector_router.py` add read-time response enrichment. The frontend types,
  `responseValidation.ts`, and `MergeReadinessPanel.tsx` validate and render the
  accepted explanation separately from the policy result. ADR-010 records the
  cross-layer decision.
- **Design decision:** Enrich both POST and GET responses after the durable run
  boundary, without adding explanation fields to the runtime repository.
  Deterministic fake generation preserves POST/GET equality and avoids a schema
  migration for non-authoritative wording.
- **Invariant or failure behavior:** The persisted policy result remains the
  only merge-readiness authority. A completed response contains either an exact
  validated explanation or a sanitized `explanation_error`; runtime failure
  contains neither. Rejected output cannot reach the browser, telemetry, or
  storage and never changes HTTP 200, runtime status, or policy decision.
- **Trade-off:** Exact templates are easy to prove and safe to expose but allow
  no free-form variation. Read-time regeneration is appropriate for the fake
  only; a future real, paid, or probabilistic provider requires a new decision
  about generation timing and persistence.
- **Validation evidence:** Eleven focused explanation tests and fourteen focused
  API integration tests passed. Complete backend discovery ran 127 tests with
  four PostgreSQL tests skipped because `TEST_DATABASE_URL` was absent.
  Frontend testing passed 10 tests; Oxlint, TypeScript/Vite production build,
  and Python `compileall` passed. No external model or network service was
  contacted.
- **Unresolved question:** Before integrating a real provider, should accepted
  explanations be generated once and persisted, or regenerated through a
  separately versioned read model?

### 2026-08-09 — Ground generated claims before rendering explanations

- **Concept:** Structural validation and semantic grounding solve different
  problems. Pydantic proves that generated fields are bounded and use known
  enums; deterministic set comparison proves those reason/action codes are
  supported and complete relative to the authoritative policy result.
- **Important syntax:** `Field(min_length=1, max_length=50)` bounds generated
  tuples. `generated_codes - required_codes` finds inventions, while
  `required_codes - generated_codes` finds omissions. Duplicate detection must
  happen before converting to sets. `tuple(dict.fromkeys(codes))` removes
  repeated policy categories while retaining deterministic policy order.
- **Implementation locations:** `app/explanations/models.py` separates
  `GeneratedExplanation` from code-only `ValidatedExplanation`.
  `validator.py` performs decision, duplicate, contradiction, support, and
  completeness checks against `MergeReadinessResult`. `service.py` parses,
  validates, and calls `render_validated_explanation()`; `fakes.py` uses that
  same path. `errors.py` owns stable sanitized failure codes, and the
  observability allowlist permits only bounded validation attributes. ADR-011
  records the decision.
- **Design decision:** Generated prose is parsed only to enforce safe bounds and
  is then discarded. Only validated codes enter deterministic text templates,
  preserving the existing API/frontend contract without claiming that
  arbitrary natural language was factually proven.
- **Invariant or failure behavior:** The policy result remains authoritative.
  Generated claims cannot change the decision, invent or omit reasons/actions,
  duplicate claims, add ready/remediation contradictions, or leave unknown
  ungrounded in missing evidence. Provider or validation failure cannot mutate
  the policy object or stored runtime run, causes no retry, and exposes only the
  existing sanitized explanation error.
- **Trade-off:** Code categories are deterministic and low-cardinality, but two
  separate policy findings with the same reason code render as one category.
  Explaining every occurrence later would require stable finding identifiers,
  not prose matching.
- **Validation evidence:** The focused explanation suite passed 21 tests.
  Complete backend discovery ran 137 tests successfully, with four PostgreSQL
  tests skipped because `TEST_DATABASE_URL` was absent. Frontend testing passed
  10 tests; Oxlint, TypeScript/Vite production build, and Python `compileall`
  passed. No external LLM, GitHub, Jira, Grafana, OTLP, or database service was
  contacted.
- **Unresolved question:** Does a future real-provider contract need stable
  per-finding IDs in addition to reason codes so it can explain repeated checks
  individually without receiving connector values?

### 2026-08-09 — Isolate a real model provider behind a deterministic adapter

- **Concept:** An SDK client and an application adapter solve different
  problems. `AsyncOpenAI` owns HTTP, authentication, timeouts, and provider
  response types. `OpenAILLMClient` translates the small PromptQL input/output
  contract and normalizes provider failures. The explanation service and
  deterministic validator remain provider-neutral.
- **Important syntax:** `await client.responses.parse(...,
  text_format=GeneratedExplanation)` asks the SDK to derive a Structured Output
  schema from Pydantic and returns typed `output_parsed`. `store=False` prevents
  ordinary response storage, `max_retries=0` disables hidden SDK retries, and a
  frozen dataclass field declared with `field(repr=False)` keeps the API key out
  of settings representation. Ordered `except` clauses matter because timeout
  is a subclass of connection failure and specific HTTP errors are subclasses
  of the generic status error.
- **Implementation locations:** `app/config.py` validates fake/OpenAI settings;
  `app/explanations/factory.py` is the only production selection point;
  `openai_client.py` owns the async Responses request and sanitized taxonomy;
  `service.py` still calls only `LLMClient` and the unchanged deterministic
  validator; observability records bounded provider/result/failure and token
  data. `test_openai_llm_client.py` injects the SDK boundary and never opens a
  network connection.
- **Design decision:** Use the official SDK with Responses Structured Outputs,
  but keep semantic grounding in PromptQL. Only the minimized decision and
  stable reason/action codes cross the provider boundary; generated prose is
  discarded and approved templates create all visible text.
- **Invariant or failure behavior:** The deterministic policy result remains
  authoritative. Authentication, permission, rate-limit, timeout, connection,
  invalid-request, refusal, invalid-structured-response, and upstream failures
  become sanitized categories. They never fall back to fake, mutate the stored
  run, expose provider details, or change a completed policy decision.
- **Trade-off:** The official SDK reduces protocol/parsing drift but adds a
  production dependency and vendor-specific adapter. Explanations are still
  read-time enrichment, so OpenAI mode can add latency and token cost to both
  POST and later GET requests. Monetary cost is not hardcoded because pricing
  varies by model and time; provider token counts are the stable measurement.
- **Validation evidence:** The focused provider/config/explanation/telemetry
  suite passed 46 tests. Complete backend discovery ran 151 tests: 147 passed
  and four PostgreSQL tests skipped because `TEST_DATABASE_URL` was absent.
  Frontend verification passed 10 tests, Oxlint, TypeScript, and the Vite build.
  No automated test contacted OpenAI or another external service.
- **Unresolved question:** Offline explanation evals and explicit prompt/model
  versioning are needed before tuning the fixed instructions or comparing
  provider/model changes on representative policy results.
### 2026-08-10 — Use one SDK without hiding two provider boundaries

- **Concept:** SDK compatibility does not mean API-operation identity. The
  OpenAI SDK can authenticate and send HTTP to Google's compatibility endpoint,
  but PromptQL must still select the correct provider, base URL, request shape,
  response fields, and token names explicitly.
- **Important syntax:** `AsyncOpenAI(base_url=..., max_retries=0)` redirects the
  SDK transport without replacing the application protocol. For Gemini,
  `await client.beta.chat.completions.parse(messages=...,
  response_format=GeneratedExplanation)` returns the typed value at
  `choices[0].message.parsed`; Chat usage uses `prompt_tokens` and
  `completion_tokens`, which the adapter maps to PromptQL's `input_tokens` and
  `output_tokens`. A `StrEnum` member keeps provider selection and telemetry
  values closed and readable.
- **Implementation locations:** `app/config.py` owns explicit `gemini` and
  `GEMINI_*` validation; `app/explanations/factory.py` fixes Google's
  compatibility URL; `gemini_client.py` owns the Chat Completions translation;
  `instructions.py`, the service, validator, and templates remain
  provider-neutral. `test_gemini_llm_client.py` and
  `test_llm_provider_factory.py` use SDK doubles and never contact Google.
- **Design decision:** Model Gemini as a separate provider while reusing the
  installed OpenAI SDK. This preserves accurate credentials and telemetry and
  avoids an arbitrary `OPENAI_BASE_URL` that could redirect a secret to an
  unsafe host. OpenAI keeps its native Responses operation; Gemini uses the
  compatibility operation Google documents.
- **Invariant or failure behavior:** The deterministic policy result remains
  authoritative. Generated prose is discarded, the Google key can go only to
  the fixed Google endpoint, and provider authentication, quota, network,
  refusal, malformed-output, or upstream failures stay sanitized. There is no
  automatic fallback and no mutation of the completed runtime run.
- **Trade-off:** Two small adapters duplicate some provider-error mapping, but
  make the incompatible request/response shapes visible to a learner and keep
  each provider easy to remove. A generic adapter would contain more branching
  and obscure which API contract is actually being used.
- **Validation evidence:** Focused provider/configuration/explanation tests ran
  43 tests successfully. Complete backend discovery ran 159 tests successfully,
  with four PostgreSQL tests skipped because `TEST_DATABASE_URL` was absent.
  Frontend verification passed 10 tests, Oxlint, TypeScript/Vite build, and
  Python `compileall`. Automated tests made no OpenAI or Google request.
- **Unresolved question:** A manual Gemini smoke test with an authorized local
  key is still required to prove the selected Google account has access to
  `gemini-2.5-flash` and sufficient quota.

### 2026-08-10 — Adapt strict claims to a provider's schema limits

- **Concept:** Provider-side structural validation and application-side trust
  validation do not need identical schemas. Google could not serve the complete
  enum-heavy PromptQL schema, so the transport uses compact request-local
  indexes while strict Pydantic and semantic validation still run afterward.
- **Important syntax:** `list[int]` produces a small JSON Schema. A tuple built
  with `dict.fromkeys(...)` deduplicates allowed codes while preserving order.
  Bounds checks reject negative/out-of-range positions before
  `GeneratedExplanation(...)` converts mapped strings into closed enums.
  `StructuredEventLogger.emit(..., llm_provider=...,
  failure_category=...)` logs only allowlisted operational categories.
- **Implementation locations:** `gemini_client.py` builds
  `GeminiExplanationInput`, parses `GeminiStructuredClaims`, maps indexes, and
  then constructs the existing strict model. `service.py`,
  `runtime_telemetry.py`, and `structured_logging.py` emit one safe failure
  event. `test_gemini_llm_client.py` proves the compact schema, mapping,
  out-of-range rejection, invalid-key classification, logging, and redaction.
- **Design decision:** Keep the clear `GEMINI_*` names and use request-local
  indexes rather than unconstrained generated code strings. This prevents the
  provider from inventing a code without reintroducing the schema complexity
  Google rejected. ADR-014 records the decision.
- **Invariant or failure behavior:** The policy result and deterministic
  validator remain authoritative. Indexes are never durable identifiers;
  duplicate or invalid positions fail closed. Logs contain provider/category
  only, and credentials, raw exceptions, prompts, outputs, payloads, request
  IDs, URLs, and headers remain absent. Logging cannot change workflow results.
- **Trade-off:** Positional claims add adapter mapping and are meaningful only
  within one request, but they retain real claim selection and completeness
  validation. Copying policy codes automatically would be simpler but would make
  the LLM validation harness meaningless.
- **Validation evidence:** Sanitized live diagnostics first reproduced Google's
  schema-state rejection and the unconstrained-code validation failure. The
  final live PromptQL path succeeded with `decision=ready`, one rendered reason,
  and no actions using the configured `gemini-2.5-flash`. The focused suite
  passed 48 tests; complete backend discovery ran 162 tests successfully, with
  four PostgreSQL tests skipped because `TEST_DATABASE_URL` was absent. Python
  `compileall` passed.
- **Unresolved question:** Live blocked and unknown cases should join a future
  provider smoke-test/evaluation set before prompt or model tuning.

### 2026-08-10 — Keep provider identity out of user-facing explanation labels

- **Concept:** A UI label should describe the guarantee the user receives, not
  the replaceable implementation behind it. PromptQL guarantees that the
  explanation passed deterministic validation, whether the configured client is
  fake, Gemini, OpenAI, or a later provider.
- **Important syntax:** JSX text between `<p>...</p>` is a literal rendered by
  React; it is not derived from response data. The focused test uses both
  `toContain(...)` and `not.toContain(...)` so the neutral label is required and
  the stale provider-specific wording cannot silently return.
- **Implementation locations:** `MergeReadinessPanel.tsx` owns the presentation
  label, while `app/config.py`, `app/explanations/factory.py`, and `app/main.py`
  continue to own restart-time provider selection. Neither
  `MergeReadinessResponse` nor the frontend `PullRequestMergeReadiness` type
  contains provider or model metadata.
- **Design decision:** Change only the hardcoded frontend wording. Adding
  provider/model fields to the public response would increase coupling and
  disclose operational configuration without changing explanation behavior.
- **Invariant or failure behavior:** The policy result remains authoritative,
  the validated explanation payload is unchanged, and provider/model identity
  remains internal. Safe telemetry may record an allowlisted provider and
  numeric token counts, but never prompts, generated output, credentials, or
  raw provider errors.
- **Trade-off:** The neutral label cannot tell a user which provider served a
  request. That is intentional for this product panel; operators use bounded
  telemetry instead. A separate authenticated diagnostics surface would be the
  appropriate future boundary if provider visibility becomes necessary.
- **Validation evidence:** Focused backend provider, OpenAI adapter, and
  explanation tests passed 38 tests. The focused panel suite passed six tests.
  A fresh application process with `PROMPTQL_LLM_PROVIDER=openai` selected
  `OpenAILLMClient`. No real OpenAI call ran because the current local
  configuration selects Gemini and contains no OpenAI key or model.
- **Unresolved question:** Should a future operator-only diagnostics endpoint
  expose provider health without expanding the public merge-readiness schema?

### 2026-08-11 — Separate controlled observations from production logging

- **Concept:** Application telemetry and eval artifacts have different jobs.
  Telemetry answers whether an operation succeeded using bounded shared labels;
  a local eval row compares deterministic expected claims with one probabilistic
  structured sample. The observation runner reuses production policy, input,
  adapter/parser, and validator boundaries without calling FastAPI or storing an
  application run.
- **Important syntax:** `argparse` flags declared with `action="store_true"`
  default to false, which makes paid-call acknowledgement explicit. Writing one
  `model_dump_json()` value followed by `"\n"` produces JSONL that can retain
  completed rows if a later case is interrupted. `finally` closes a real async
  client, while an injected fake has no close method. A frozen Pydantic record
  makes prompts, prose, identities, and raw errors structurally impossible to
  serialize because those fields do not exist.
- **Implementation locations:** `app/evals/cases.py` builds eleven stable cases
  from fake connector facts; `models.py` defines the minimized local record;
  `observation.py` owns preflight, acknowledgement, provider execution,
  validation, and JSONL writing. `required_explanation_claims()` in
  `app/explanations/validator.py` is shared by the validator and eval ground
  truth. `test_explanation_eval_observation.py` proves stable IDs, deterministic
  labels, fake dry-run, gating, serialization, failure separation, and content
  exclusion without opening a network connection.
- **Design decision:** Stage 1 records provisional `stage1-current` and
  `stage1-observation-v1` labels rather than prematurely declaring a stable
  production prompt contract. Inspected cases become development evidence;
  Stage 2 must introduce separate unseen holdout cases, formal graders,
  repeated sampling, thresholds, baselines, and durable prompt versioning.
- **Invariant or failure behavior:** Expected claims always come from the pure
  policy plus the validator's shared requirement derivation. Missing paid-call
  acknowledgement prevents client construction. Reports never contain API
  keys, headers, prompts, generated prose, connector payloads, repository/Jira
  identity, raw provider responses, exception text, or cost estimates.
- **Trade-off:** Serial execution and immediate JSONL flushing make the first
  experiment easy to inspect and preserve partial evidence, but one sample per
  case cannot measure reliability. The local report may contain provider/model
  identity for comparison, so it is gitignored rather than treated as
  application telemetry or a committed dataset.
- **Validation evidence:** Focused observation tests passed 8 tests. Complete
  backend discovery ran 170 tests successfully, with four
  PostgreSQL tests skipped because `TEST_DATABASE_URL` was absent. Frontend
  verification passed 10 tests, Oxlint, TypeScript/Vite build, and Python
  `compileall`. The fake dry-run wrote 11 ignored JSONL rows. Real-provider
  preflight validated the configured Gemini settings and reported zero calls and
  a 5,632-token maximum output cap; no paid provider call was made.
- **Live observation evidence:** After explicit approval and key rotation, one
  eleven-case Gemini pass produced seven exact validator passes and four
  sanitized `rate_limit` failures. The failures had no generated candidate, so
  `schema_valid=false` and `validator_result=not_run` correctly distinguish a
  provider availability/quota problem from invalid or ungrounded explanation
  content. No retries were attempted because they would have been additional
  unapproved samples.
- **Unresolved question:** After inspecting the first live samples, which
  unseen fixture variations best test generalization without reproducing the
  development combinations?

### 2026-08-11 — Separate eval operation from candidate quality

- **Concept:** A planned provider call is an attempt even when it returns no
  candidate. Provider-success and attempt-success rates therefore use all
  planned calls, while schema, decision, code-set, validator, and model-quality
  rates use only returned candidates. This preserves the Stage 1 truth that
  Gemini had `7/11` provider success and `7/7` exact candidate quality.
- **Important syntax:** Nested `for` loops make the case/sample order explicit;
  `range(1, samples_per_case + 1)` gives stable one-based sample numbers.
  `await sleep(delay)` occurs only when the current attempt is not the final
  planned attempt, so pacing adds no retry and is excluded from latency measured
  inside `observe_case()`. Set intersection/difference produce micro true
  positives, false positives, and false negatives, while the strict validator
  separately rejects duplicate tuple entries.
- **Implementation locations:** `app/evals/cases.py` owns the disjoint
  development and holdout inputs; `observation.py` classifies one attempt;
  `graders.py` owns pure aggregation and V1 thresholds; `reporting.py` owns
  incremental/redacted artifacts and compatible baselines; `runner.py` owns
  preflight, repeated execution, pacing, gating, and exit semantics. Prompt
  identity lives beside the production instructions rather than in the CLI.
- **Design decision:** Use local deterministic graders instead of an LLM judge
  or hosted eval service. Normal holdout artifacts expose aggregate outcomes
  only; `--debug-holdout-details` is an explicit acknowledgement that inspecting
  case claims spends the holdout. Baselines reject incompatible prompt,
  dataset, provider, model, sample-count, or model-setting identities.
- **Invariant or failure behavior:** One planned sample creates exactly one
  outcome and no failure is retried. The completed JSON report is written before
  threshold exit code 1. Execution completion, quality thresholds, provider
  operation, and combined release status remain distinct. Artifacts exclude
  prompts, prose, credentials, connector identities/payloads, raw responses,
  exception text, and unversioned cost estimates.
- **Trade-off:** Three samples and a one-second default delay are inexpensive
  and reduce burst pressure, but provide limited statistical confidence and add
  wall-clock time. Requiring zero provider failures is a deliberately strict V1
  operational threshold that may need measured revision after the first formal
  baseline.
- **Validation evidence:** Twenty-six focused eval tests passed. Complete
  backend discovery ran 188 tests with four PostgreSQL tests skipped because
  `TEST_DATABASE_URL` was absent. A 33-sample fake development run passed every
  threshold. Configured Gemini preflight reported 33 development requests with
  16,896 maximum output tokens and 18 holdout requests with 9,216 maximum output
  tokens; both preflights made zero external calls. Frontend verification and
  final hygiene checks passed: 10 frontend tests, Oxlint, the TypeScript/Vite
  build, Python `compileall`, and `git diff --check`.
- **Unresolved question:** After the first approved complete provider run,
  should the zero-provider-failure operational threshold remain strict or be
  replaced by a separately versioned measured availability threshold?

### 2026-08-12 — Preserve execution provenance and typed failure state end to end

- **Concept:** Operational provenance is different from business evidence. The
  policy still consumes only normalized GitHub/Jira facts, while `RunSources`
  records which bounded implementations supplied a run. Likewise, an HTTP 500
  failed run is an execution result with a run ID and step history, not an
  `unknown` merge-readiness decision.
- **Important syntax:** Python `StrEnum` gives JSON-friendly closed values while
  Pydantic rejects unknown strings. SQLAlchemy `Mapped[str | None]` creates
  nullable relational columns, and Alembic `create_check_constraint()` keeps
  the database vocabulary aligned. In TypeScript, a discriminated union on
  `status: 'completed' | 'failed'` lets React access a non-null policy result
  only in the completed branch. Runtime type guards reconstruct network data
  without an unchecked cast.
- **Implementation locations:** `app/runtime/models.py` owns `RunSources`;
  `workflows/merge_readiness.py` captures it before the first commit;
  `database/models.py`, `postgres_run_repository.py`, and migration
  `20260812_0002` persist and reconstruct it; `connector_router.py` reports the
  provider used for read-time explanation enrichment. Frontend types,
  `responseValidation.ts`, `api.ts`, and `MergeReadinessPanel.tsx` preserve and
  render completed and failed runtime states.
- **Design decision:** Three nullable, checked columns were selected instead of
  generic JSONB metadata. This keeps V1 queryable and bounded, avoids secrets
  and uncontrolled identities, and leaves old rows readable. Explanation
  output remains read-time and unpersisted; therefore the HTTP response reports
  the provider used for that enrichment.
- **Invariant or failure behavior:** Provenance cannot change the deterministic
  decision. A completed run has a policy result and HTTP 200; a failed run has
  a sanitized error, `result=null`, and HTTP 500. The frontend never converts
  one into the other. Unknown or absent legacy source fields display as source
  `unknown`, not policy `unknown`.
- **Observability implication:** Explanation spans include prompt ID/version,
  provider, and a short SHA-256 configured-model fingerprint for operational
  traceability without exporting an arbitrary environment value. Those values
  are excluded from metric labels, and prompt/output content remains excluded
  from all telemetry.
- **Trade-off:** New source families require a deliberate schema migration, and
  a later GET can use a different explanation provider because explanations are
  not persisted. This is narrower and safer than an unbounded metadata system;
  versioned explanation persistence remains postponed.
- **Validation evidence:** `uv run python -m unittest discover -s tests -v`
  ran 193 tests successfully with five PostgreSQL tests skipped because
  `TEST_DATABASE_URL` was absent. `bun run test:web` passed 14 tests; web lint
  and build passed. `compileall`, one-head Alembic inspection, offline migration
  SQL, `git diff --check`, and a sensitive-pattern scan passed. The fake
  development eval completed 33/33 attempts and all release thresholds without
  an external provider call.
- **Unresolved question:** Should a later milestone persist the validated
  explanation and exact model identity so GET never performs a second provider
  call, or should explanations remain intentionally read-time?

### 2026-08-12 — Separate model quality from provider reliability in release evals

- **Concept:** A completed evaluation can demonstrate perfect candidate quality
  and still fail release readiness because provider reliability is measured on
  every planned attempt. Candidate metrics use only returned candidates, while
  operational metrics retain rate-limited attempts in their denominator.
- **Important syntax:** The runner's `--acknowledge-paid-calls` flag is an
  explicit network/cost gate, and `--save-baseline <path>` records the exact
  prompt, dataset, provider, configured model, settings, and sample-count
  identity. A command exit code of `1` means execution completed but at least
  one release threshold failed; it is different from a configuration failure.
- **Implementation evidence:** `app/evals/runner.py` preserved 33 incremental
  observations and wrote the completed development report before returning
  exit code 1. `app/evals/graders.py` independently evaluated candidate quality
  and the zero-provider-failure operational threshold.
- **Decision and invariant:** The untouched holdout was not run after the
  development release gate failed. Holdout evidence must never be spent to
  diagnose a development-stage provider or prompt problem.
- **Trade-off:** Requiring zero provider failures makes V1 promotion strict and
  easy to interpret, but one transient rate limit can block a release even when
  every returned candidate is correct. Changing pacing, quota, or the threshold
  requires a deliberate follow-up rather than silently retrying or excluding
  failed attempts.
- **Validation evidence:** The approved `gemini-3.1-flash-lite` development run
  completed 33/33 attempts. Thirty provider responses achieved 100% schema,
  decision, reason-set, action-set, validator, and end-to-end candidate quality;
  three `rate_limit` failures produced 90.9% provider success, so quality passed
  while operational and release thresholds failed. No holdout call was made.
- **Unresolved question:** Should the next approved run keep the one-second
  pacing with higher provider quota, or version a slower pacing configuration
  before reconsidering the strict zero-failure threshold?

### 2026-08-13 - Annotate the FastAPI composition root without changing behavior

- **Concept:** Teaching comments should explain architecture boundaries and
  invariants rather than narrate individual statements. Foldable `# region`
  blocks use a consistent `Purpose`, `Flow`, `Key syntax`, `Why here`, and
  `Watch out` shape to make the FastAPI composition root readable.
- **Important syntax:** `@asynccontextmanager` turns the nested async function
  into FastAPI's application-lifespan context manager; code before `yield` is
  startup and `finally` still runs on shutdown or startup failure.
- **Implementation locations:** `services/api/app/main.py` now identifies its
  typed HTTP error handlers, health route, dependency composition, lifespan,
  route registration, and ASGI entry point.
- **Design decision:** Use normal-depth regions with only the applicable parts
  of the five-part shape, rather than line-by-line notes. This gives learners
  the request-to-response map without altering the public API or duplicating
  obvious Python syntax.
- **Invariant or failure behavior:** The exception status mappings, startup
  database verification, resource shutdown, application state fields, and
  imported `app` entry point remain executable code with identical tokens.
- **Trade-off:** Regions add visual detail, but the checkout-local clean filter
  strips them from Git's stored representation; it leaves harmless collapsed
  blank-line artifacts in the filtered diff.
- **Validation evidence:** The focused
  `uv run python -m unittest tests.unit.test_application_startup_logging -v`
  test passed, `uv run python -m py_compile app/main.py` passed, and a Python
  token comparison confirmed the HEAD and working copy have identical
  executable tokens after comments are ignored.
- **Unresolved question:** Should the clean filter be adjusted in a separate
  task so multiline teaching regions do not create filtered blank-line diffs?

### 2026-08-13 - Explain the FastAPI routing boundary without changing behavior

- **Concept:** A router is an HTTP adapter, not the workflow itself. It validates
  request shapes, resolves dependencies, delegates to application services, and
  maps results to public status codes and response models.
- **Important syntax:** `Annotated[T, Depends(provider)]` asks FastAPI to build
  a typed dependency graph before a route runs. `await` lets a route pause for
  async workflow or explanation work without blocking other event-loop tasks.
- **Implementation locations:** `services/api/app/api/v1/connector_router.py`
  now has normal-depth regions for connector, telemetry, repository, and
  explanation dependencies; workflow assembly; response enrichment; and all
  four public route handlers.
- **Design decision:** Explain dependency providers separately from route
  handlers and keep the response-enrichment boundary explicit. This matches the
  real request flow and makes it clear that optional LLM wording cannot alter
  the durable policy result.
- **Invariant or failure behavior:** Production repository lookup never falls
  back to memory; unavailable persistence remains a sanitized 503. A failed
  workflow run is a persisted execution record returned as HTTP 500, not an
  `unknown` policy decision. Read-time explanations do not mutate stored runs.
- **Trade-off:** More regions make the HTTP path longer to scan, but stable
  `Purpose` through `Watch out` labels let a learner skip directly to the
  relevant concern without reading a line-by-line narration.
- **Validation evidence:** `test_merge_readiness_api.py` and
  `test_database_config.py` are the focused behavior checks. Compilation and an
  executable-token comparison verify that annotation changes do not alter the
  router's Python behavior.
- **Unresolved question:** If explanation retrieval becomes expensive for real
  providers, should a future design persist a validated rendered explanation,
  or keep the current read-time enrichment boundary?

### 2026-08-13 - Explain a durable async workflow without changing behavior

- **Concept:** An application workflow coordinates side effects while the domain
  policy remains pure. It records each state transition around connector and
  policy work so a response can distinguish a completed decision from a failed
  execution.
- **Important syntax:** `asyncio.to_thread(...)` lets async code wait for the
  synchronous repository without blocking the event loop. Tuple unpacking and
  `(*run.steps, step)` produce updated immutable snapshots, while `yield` is
  not involved in this workflow; FastAPI lifespan owns application resources.
- **Implementation locations:** `services/api/app/workflows/merge_readiness.py`
  now has normal-depth regions for injected collaborators, persistence helpers,
  state transitions, telemetry, GitHub/Jira boundaries, and policy completion.
- **Design decision:** Keep the explicit named sequence GitHub -> Jira ->
  policy instead of a generic step loop. The fixed order makes the business
  path, evidence ownership, state history, and failure behavior easier to read.
- **Invariant or failure behavior:** A terminal failed step and failed run save
  together; a terminal policy step and completed run save together. Connector
  unavailability remains optional evidence, but unexpected connector or policy
  errors become sanitized failed runs. Terminal telemetry follows persistence.
- **Trade-off:** Many small helpers make the service longer than one linear
  method, but each helper names one transition boundary and permits focused
  tests for ordering, atomic terminal state, and safe error handling.
- **Validation evidence:** `test_merge_readiness_workflow.py` proves ready,
  blocked, failed-connector, failed-policy, ordered-step, and terminal-save
  behavior. Compilation and a clean-filtered token comparison protect the
  comment-only change.
- **Unresolved question:** If future steps require retries or cancellation,
  should that extend this state machine directly or introduce a separate job
  execution boundary?

### 2026-08-14 - Explain structural connector contracts without changing behavior

- **Concept:** A Python `Protocol` describes the shape an implementation must
  have without requiring inheritance. The workflow can therefore use fake and
  HTTP connectors through the same GitHub and Jira contracts.
- **Important syntax:** An `async def` protocol method is awaited by callers;
  the `...` body declares the required signature but provides no implementation.
  `source: ConnectorSource` is a required typed attribute, not a method call.
- **Implementation locations:** `services/api/app/connectors/protocols.py` now
  explains both provider-neutral protocols and their asynchronous lookup methods.
- **Design decision:** Keep GitHub request lookup and Jira issue-key lookup as
  separate minimal contracts. Each provider can normalize its own API boundary,
  while the workflow receives typed facts instead of vendor-specific JSON.
- **Invariant or failure behavior:** Live and fake implementations report an
  accurate bounded source and never silently substitute fixture facts. Unknown
  or unavailable data leaves through typed connector errors or missing evidence;
  policy decides what incomplete evidence means.
- **Trade-off:** Two protocols repeat a small `source` attribute, but make the
  different input contracts visible and allow GitHub/Jira fake-live selection to
  stay independent.
- **Validation evidence:** `test_connector_contracts.py` covers validated
  fixtures, typed unknown-fixture errors, and deterministic fake outputs.
  Compilation and a clean-filtered token comparison verify comment-only changes.
- **Unresolved question:** If a future provider supplies both pull requests and
  issues, should it implement both focused protocols or introduce a new adapter
  that composes them?

### 2026-08-14 - Explain connector construction at the application boundary

- **Concept:** A factory is a narrow composition boundary: validated settings
  select concrete fake or HTTP implementations, while workflows consume only
  the provider-neutral protocols.
- **Important syntax:** `httpx.AsyncClient` owns an async connection pool and
  must be closed by application lifespan. `httpx.BasicAuth` supplies Jira
  credentials outside the URL. An enum identity check (`is`) selects one mode.
- **Implementation locations:** `services/api/app/connectors/factory.py` now
  explains GitHub/Jira HTTP-client construction and fake/live connector choice.
- **Design decision:** Keep independent GitHub and Jira factory functions.
  This permits every fake/live source combination and keeps provider credentials,
  pool limits, timeouts, and protocol construction out of workflow code.
- **Invariant or failure behavior:** Live mode requires complete validated
  configuration and an application-scoped HTTP client. A missing client or
  credential raises a typed configuration error; no live path falls back to
  fixture facts. Redirects remain disabled at both external-service boundaries.
- **Trade-off:** Two similar factory pairs repeat some selection logic, but they
  expose each provider's different auth and timeout needs more clearly than a
  generic connector factory with conditional options.
- **Validation evidence:** GitHub and Jira factory tests cover fake defaults,
  live implementation selection, explicit Jira timeouts, safe settings errors,
  and independent source combinations. Compilation and a teaching-region token
  comparison protect the comment-only change.
- **Unresolved question:** If connection-pool limits need runtime tuning, should
  each provider gain separate settings or should a bounded shared transport
  settings object be introduced?

### 2026-08-14 - Explain read-only HTTP connector adapters without changing behavior

- **Concept:** An HTTP connector is an anti-corruption boundary. It translates
  provider REST payloads and status codes into validated internal facts and
  stable typed errors before workflow or policy code sees them.
- **Important syntax:** `await` suspends a connector while HTTP I/O is pending.
  Pydantic `model_validate()` rejects malformed external JSON. `quote()` encodes
  path segments, and `fullmatch()` validates an entire Jira key.
- **Implementation locations:** `github_http.py` now explains aggregation of PR,
  review, requirement, check-run, and status evidence, bounded pagination, and
  GitHub status mapping. `jira_http.py` explains selected-field issue lookup,
  status-category normalization, bounded retry metadata, and safe telemetry.
- **Design decision:** Normalize provider shapes inside separate adapters and
  return repository-owned models. GitHub merges overlapping REST evidence;
  Jira maps universal status categories while retaining custom display evidence.
- **Invariant or failure behavior:** Raw payloads, URLs, headers, credentials,
  and private exceptions never become public errors or telemetry. Inaccessible
  optional evidence remains explicitly unknown; malformed, rate-limited, timed
  out, or unexpected provider operations become sanitized typed failures.
- **Trade-off:** Bounded pagination and multiple validation helpers add code,
  but prevent unbounded work, partial truncation, and accidental coupling of
  workflow policy to changing GitHub or Jira response formats.
- **Validation evidence:** Mock-transport GitHub and Jira connector tests cover
  request construction, pagination, normalization, error categories, and
  telemetry without live provider calls. Compilation and teaching-region token
  comparisons verify comments do not change executable behavior.
- **Unresolved question:** If GitHub adds a new required-check API, should the
  adapter merge it into the current worst-status algorithm or version a new
  explicit evidence field first?

### 2026-08-14 - Explain immutable connector facts without changing behavior

- **Concept:** Provider-neutral Pydantic models form a trust boundary. Adapters
  normalize external data into frozen, closed-vocabulary facts; workflow and
  policy can then operate without parsing raw provider JSON.
- **Important syntax:** `Annotated` attaches reusable validation metadata to a
  base type. `StrEnum` is a closed Python enum that serializes as a JSON string.
  A `model_validator(mode="after")` checks a complete Pydantic model across
  several fields after individual field validation succeeds.
- **Implementation locations:** `services/api/app/connectors/models.py` now
  explains shared aliases, strict frozen base configuration, state enums,
  connector request identity, GitHub/Jira snapshots, and evidence availability.
- **Design decision:** Represent unavailable reviews/checks with explicit
  `*_known` flags and closed `UNKNOWN` states rather than substituting empty
  collections or a false negative. This keeps missing provider access visible
  to policy and avoids false-ready decisions.
- **Invariant or failure behavior:** Extra fields fail validation, snapshots are
  immutable, PR numbers are true positive integers, and unknown review/check
  evidence cannot contain approval or check conclusions. Jira blocker state
  remains unknown unless an implementation supplies an explicit supported fact.
- **Trade-off:** More small types and validators make adapters construct more
  objects, but give every fake, HTTP, persistence, and policy path one precise,
  testable vocabulary instead of ad-hoc dictionaries.
- **Validation evidence:** Connector-contract tests round-trip fixtures, reject
  invalid enum/request values, and prove typed unknown-fixture behavior.
  Compilation and a teaching-region token comparison protect comment-only edits.
- **Unresolved question:** If additional provider evidence becomes optional,
  should it follow the current `*_known` convention or require a more general
  explicit evidence-status model?

### 2026-08-14 - Explain deterministic policy evaluation without changing behavior

- **Concept:** A pure policy function converts already-normalized facts into a
  decision without I/O, persistence, telemetry, clocks, or provider SDKs. It
  accumulates evidence and findings before selecting one terminal decision.
- **Important syntax:** Optional model inputs represent unavailable connectors;
  list accumulation preserves all findings before immutable tuples enter the
  result. Ordered `if`/`elif` branches encode `BLOCKED > UNKNOWN > READY`.
- **Implementation locations:** `services/api/app/policy/evaluator.py` now
  explains evidence IDs, blocker/action pairing, missing information, GitHub
  lifecycle/CI/review rules, Jira identity/rules, and final precedence.
- **Design decision:** Evaluate every applicable rule and preserve every verified
  blocker rather than returning on the first failure. The first blocker remains
  the primary reason, while the complete list supports remediation and evidence.
- **Invariant or failure behavior:** Missing evidence never becomes a verified
  blocker or implicit success. A verified blocker takes precedence over unknown
  evidence. Jira facts are evaluated only when their key matches GitHub's link;
  unknown Jira blocker state is neither blocked nor proven not blocked.
- **Trade-off:** Explicit rule branches are longer than a generic rule engine,
  but make evidence mapping, precedence, messages, and pending actions visible
  and straightforward to test without framework abstractions.
- **Validation evidence:** `test_merge_readiness_policy.py` covers every blocker,
  simultaneous blockers, unknown inputs, mismatched Jira evidence, deterministic
  output, decision precedence, and evidence references. Compilation and a
  teaching-region token comparison protect comment-only edits.
- **Unresolved question:** As rule count grows, when would data-driven rule
  definitions improve maintainability without hiding precedence and evidence
  construction from learners?

### 2026-08-14 - Explain immutable runtime state machines without changing behavior

- **Concept:** Runtime safety has two layers. Transition maps define which status
  movements are legal; Pydantic validators define which fields make each status
  internally coherent. Immutable snapshots make every lifecycle change explicit.
- **Important syntax:** Dictionary-of-set transition maps express directed state
  edges. `model_dump()` plus `model_validate()` creates a changed frozen copy.
  `model_validator(mode="after")` compares status with timestamps, errors, and result.
- **Implementation locations:** `runtime/models.py` now explains lifecycle enums,
  sanitized errors, bounded source provenance, step/run snapshots, and validators.
  `runtime/state.py` explains allowed edges, replacement helpers, initial factories,
  and run/step transition functions.
- **Design decision:** Keep transition legality separate from snapshot validation.
  This makes the state graph readable while ensuring database reconstruction and
  direct model creation receive the same field-level invariants as live execution.
- **Invariant or failure behavior:** Terminal records cannot return to running.
  Completed runs contain a result and no error; failed runs contain an error and
  no result. Pending/running records cannot contain terminal metadata. A blocked
  policy decision remains a completed execution.
- **Trade-off:** Rebuilding and validating complete snapshots allocates more
  objects than mutation, but makes history, persistence, tests, and concurrency
  reasoning clearer and prevents partial in-memory updates.
- **Validation evidence:** `test_runtime_state.py` proves bounded provenance,
  legal construction, and terminal-state irreversibility. Compilation and
  teaching-region token comparisons protect the comment-only edits.
- **Unresolved question:** Cancellation exists in the model but has no public
  API or worker coordination yet; what ownership boundary should initiate and
  durably confirm cancellation before enabling that state?

### 2026-08-14 - Trace persistence, grounded explanations, and telemetry boundaries

- **Concept:** Production boundaries can be composed around authoritative domain
  behavior: repositories own durability, adapters own providers, deterministic
  validators own trust, and telemetry decorators observe without changing results.
- **Important syntax:** `Protocol` provides structural dependency inversion;
  SQLAlchemy `Mapped[...]` declares runtime ORM fields; conditional SQL UPDATE plus
  `rowcount` implements optimistic concurrency; `@contextmanager` and `yield` own
  span lifecycle; `try/except/else` separates provider failure from safe parsing.
- **Implementation locations:** Teaching comments in `runtime/repository.py`,
  `observability/observed_run_repository.py`, `database/postgres_run_repository.py`,
  `database/models.py`, `explanations/`, and `observability/` trace these boundaries.
- **Design decision:** Keep generated prose and provider/SQL details outside the
  trusted result. Only policy-supported codes reach backend templates, and only
  bounded categories and labels reach telemetry.
- **Invariant or failure behavior:** Terminal runtime state is exposed only after
  commit; stale writers fail conditional updates; explanation failure cannot mutate
  policy or persistence; telemetry setup/export failure degrades without changing HTTP.
- **Trade-off:** Explicit mappers, validators, adapters, and telemetry wrappers add
  code, but make concurrency, trust, redaction, and vendor coupling independently
  testable instead of hiding them behind one large infrastructure service.
- **Validation evidence:** Python compilation, focused runtime/explanation/
  observability tests, `git diff --check`, and executable-token comparison verify
  that this annotation pass changes teaching text without changing Python behavior.
- **Unresolved question:** If explanations become persisted, which component should
  own prompt/model/template versioning without weakening the policy authority boundary?

### 2026-08-16 - Add an OpenAI-compatible provider without confusing identity

- **Concept:** API compatibility belongs inside an adapter; it does not change
  provider identity or move trust into the SDK. Groq reuses `AsyncOpenAI`, while
  configuration, telemetry, eval reports, run provenance, and failures say `groq`.
- **Important syntax:** Passing a Pydantic class as Chat Completions
  `response_format` makes the installed SDK build a strict JSON Schema. A Python
  `Protocol` describes only the nested SDK methods the adapter calls, allowing
  small async test doubles without constructing a network client.
- **Implementation locations:** `config.py`, `explanations/groq_client.py`,
  `explanations/factory.py`, `runtime/models.py`, `database/models.py`, migration
  `20260816_0003`, runtime telemetry, frontend response validation, and the
  Groq/provider/eval/API tests.
- **Design decision:** Use the existing OpenAI SDK with Groq's fixed compatibility
  URL and required `GROQ_MODEL`; recommend `openai/gpt-oss-20b` for the bounded
  V1 workload. The owner approved extending durable provenance through a narrow
  constraint migration instead of making Groq eval-only.
- **Invariant or failure behavior:** SDK retries stay disabled. A 429 is one
  provider failure; malformed candidate structure is separate from a schema-valid
  semantic validation failure. Generated prose remains untrusted and discarded,
  and only policy-supported complete codes reach deterministic templates.
- **Trade-off:** A separate adapter repeats some SDK error mapping, but keeps
  Groq-specific API behavior isolated. Downgrade cannot represent Groq rows and
  therefore fails transactionally rather than silently erasing their provenance.
- **Validation evidence:** Focused configuration, adapter, runtime, database,
  API, and eval tests; offline Alembic SQL; complete backend discovery;
  `compileall`; one-head inspection; and `git diff --check` provide evidence.
- **Unresolved question:** After an explicitly approved development eval, does
  20B meet the existing candidate-quality thresholds, or does evidence justify
  the higher latency and token price of 120B?

### 2026-08-16 - Observe a workflow through snapshots before introducing events

- **Concept:** A snapshot tells the dashboard what is true now; an event would
  tell it what happened. V1 already writes meaningful immutable snapshots, so
  a dashboard can poll the existing run resource without SSE, WebSockets, or a
  new event table.
- **Important syntax:** `asyncio.create_task()` schedules an awaitable in the
  current process; `asyncio.gather(..., return_exceptions=True)` lets lifespan
  shutdown cancel and await those tasks. In the browser, `AbortController`
  cancels an in-flight fetch, while a recursive `setTimeout` after each response
  prevents overlapping polls that `setInterval` could create.
- **Implementation locations:** The additive start contract is in
  `api/v1/connector_router.py` and `api/v1/models.py`; the existing workflow
  now separates pending-snapshot creation from continuation in
  `workflows/merge_readiness.py`; `runtime/live_run_tasks.py` owns only task
  references. The frontend validates active snapshots in
  `responseValidation.ts`, polls through `runPolling.ts`, and renders
  `/runs/:runId` with `RunDashboardPage.tsx`.
- **Design decision:** Preserve the synchronous V1 POST and add a distinct
  `202 Accepted` route. `202` means the pending snapshot committed and work was
  accepted, not that policy execution completed. ADR-018 records why this is a
  local/developer boundary rather than durable worker execution.
- **Invariant or failure behavior:** PostgreSQL snapshots remain the browser's
  source of truth. Temporary dashboard refresh errors never become workflow
  failures. Only backend policy can supply ready/blocked/unknown. Raw JSON is
  rendered only after frontend validation, and runtime errors stay sanitized.
- **Trade-off:** One polling read per active dashboard per second is simple and
  inspectable at this small scale, but not suitable for high fan-out. A process
  crash stops local tasks; committed snapshots survive but work does not resume.
- **Validation evidence:** Focused API/workflow/task-registry tests verify
  pending acceptance, GET-visible transitions, typed failure, synchronous
  compatibility, and shutdown cancellation. Frontend tests verify transport
  validation, serialized terminal-aware polling, abort cleanup, refresh-error
  separation, and dashboard rendering; frontend build and lint provide type and
  bundling evidence.
- **Unresolved question:** When V2 needs history, replay, crash recovery, or
  many live viewers, what durable `RunEvent` shape and SSE cursor contract can
  extend snapshots without exposing private model reasoning?

### 2026-08-16 - Model investigation facts separately from hypotheses

- **V2 milestone:** V2.1 Investigation Domain Model.
- **Concept:** A domain contract encodes meaning and valid relationships, not
  transport, storage, or runtime lifecycle. Typed facts are deterministically
  supported findings; hypotheses remain candidate explanations whose grounding
  does not prove objective correctness.
- **Important syntax:** `Annotated[..., Field(discriminator="fact_type")]`
  makes Pydantic select one fact schema from a union using a stable literal tag.
  `StrEnum` restricts codes while preserving JSON strings, and
  `@model_validator(mode="after")` validates relationships across already parsed
  immutable values.
- **Implementation locations:** `investigations/models.py` defines requests,
  three fact variants, hypotheses, unknowns, actions, and result invariants;
  `test_investigation_models.py` proves valid and invalid construction. ADR-019
  records why runtime, evidence, and LLM integration remain separate.
- **Design decision:** Use a small discriminated fact union and an extensible
  constrained hypothesis code. This preserves machine-readable fact semantics
  without pretending the project already knows a universal root-cause taxonomy.
- **Invariant or failure behavior:** Every fact cites a future evidence ID;
  entity IDs are unique; internal references resolve; grounded or contradicted
  hypotheses cite facts/evidence; and insufficient evidence can produce explicit
  unknowns without an invented hypothesis.
- **Trade-off:** Adding a fact kind requires an explicit union change and tests,
  but consumers never need to parse prose to discover which fields are valid.
  Evidence existence cannot be validated until V2.2 owns evidence records.
- **Validation evidence:** `.venv\Scripts\python.exe -m unittest
  tests.unit.test_investigation_models -v`, complete backend discovery,
  `compileall`, and `git diff --check` validate the domain boundary and V1
  compatibility.
- **Unresolved question:** Which provenance fields must V2.2 evidence expose so
  a fact builder can prove both evidence existence and deterministic derivation?

### 2026-08-17 - Preserve source observations before deriving facts

- **V2 milestone:** V2.2 First-Class Evidence and Provenance Domain Model.
- **Concept:** Evidence is an immutable normalized source observation; a fact is
  a deterministic conclusion derived from evidence. Provenance records where an
  observation came from and distinguishes source-event time from retrieval time.
- **Important syntax:** Pydantic `AwareDatetime` rejects naive timestamps.
  `Annotated[Union, Field(discriminator="content_type")]` validates exactly one
  typed content variant, while an `after` model validator checks envelope kind,
  logical source, and aggregate cross-references.
- **Implementation locations:** `investigations/models.py` contains the envelope,
  provenance, five content variants, and `InvestigationResult` reference checks;
  `test_evidence_models.py` covers valid and invalid evidence states. ADR-020
  records the envelope decision and why V1 `EvidenceReference` remains unchanged.
- **Design decision:** Share provenance in one envelope and keep content as a
  small discriminated union. This avoids repeated audit fields without accepting
  an arbitrary `dict[str, Any]` or provider response schema.
- **Invariant or failure behavior:** Evidence is frozen; IDs are unique;
  source/kind/content agree; timestamps are timezone-aware; facts and direct
  hypothesis evidence links resolve within one result; unavailable data creates
  `MissingInformation`, not evidence with `None` content.
- **Trade-off:** Adding a content kind requires an explicit model, enum, source
  rule, and test. This is more work than accepting a dictionary, but it gives
  deterministic validation, safer serialization, comparable eval inputs, and
  clearer migrations. Retrieval may appear before observed time by a small
  amount because strict ordering would mishandle distributed clock skew.
- **Validation evidence:** Focused V2.1/V2.2 tests, application/test compilation,
  complete backend unittest discovery, forbidden-pattern review, and
  `git diff --check` prove the boundary without provider or persistence calls.
- **Unresolved question:** In V2.3, should changed-file evidence identify only a
  pull request, or also require a specific head commit to make repeated PR reads
  distinguishable without introducing evidence versioning prematurely?

### 2026-08-17 - Normalize GitHub code changes behind a focused capability

- **V2 milestone:** V2.3 GitHub Code/Diff Evidence.
- **Concept:** An anti-corruption layer validates GitHub's provider model and
  translates only investigation-relevant fields into immutable V2 evidence.
  Provider capability remains separate from a future planner-visible tool.
- **Important syntax:** Python `Protocol` expresses structural async capability;
  private Pydantic response models ignore unrelated provider fields while
  validating required ones; a compiled regex parses unified-diff hunk headers;
  injected `Callable[[], datetime]` clocks make retrieval provenance deterministic.
- **Implementation locations:** `connectors/protocols.py` defines the focused
  interface; `github_code_http.py` normalizes HTTP data; `github_diff.py` parses
  bounded hunks; `github_code_fakes.py` supplies deterministic evidence;
  `investigations/models.py` owns PR/file/hunk domain contracts; ADR-021 records
  why the V1 connector remains unchanged.
- **Design decision:** Use three focused read-only operations and dedicated fake/
  HTTP implementations while reusing GitHub settings, the application-scoped
  client, sanitized errors, and telemetry. This follows Interface Segregation
  without creating planner tools or a generic raw-JSON client.
- **Invariant or failure behavior:** Raw JSON, headers, profiles, emails, URLs,
  and provider exceptions never cross the adapter. File counts and rename paths
  agree; hunk lines consume declared old/new ranges; missing patch differs from
  malformed patch; page/patch bounds raise `GitHubIncompleteResultError` rather
  than returning partial evidence as complete.
- **Trade-off:** Explicit response/content models and a small parser require more
  code than `dict[str, Any]`, but downstream facts/evals receive predictable,
  bounded structures. The initial 1,000-file local page budget may reject a
  legitimate very large PR; that is safer than silent truncation and is
  reversible when measured workloads justify another bound.
- **Validation evidence:** 67 new/V2 focused tests, 95 combined V1/V2 connector
  regression tests, and 278 complete backend tests passed; six PostgreSQL tests
  were environment-guarded. Compilation, comment-pass reruns, and final diff
  checks are recorded when the milestone closes.
- **Unresolved question:** Should V2.6 derive file facts from every returned file,
  or accept an explicit deterministic relevance filter before fact construction?

### 2026-08-17 - Separate operational evidence from observability export

- **V2 milestone:** V2.4 IncidentSource and normalized operational evidence.
- **Concept:** A provider-neutral port translates incident-provider observations
  into immutable evidence without making Grafana, Sentry, Datadog, PromQL, or
  LogQL part of the investigation domain. Operational telemetry export is not
  the same capability as querying provider data for an investigation.
- **Important syntax:** `Protocol` describes the four asynchronous source
  capabilities structurally; Pydantic `AwareDatetime` and `model_validator`
  enforce timezone-aware ordered telemetry windows and source-specific content
  invariants; frozen tuple filters make fixture requests stable dictionary keys.
- **Implementation locations:** `connectors/models.py` owns bounded provider-
  neutral requests; `connectors/protocols.py` defines `IncidentSource`;
  `connectors/incident_fakes.py` supplies deterministic fixtures; and
  `investigations/models.py` adds incident, deployment, stack/error, and
  telemetry-window content to the shared V2.2 envelope.
- **Design decision:** Use four semantic operations instead of one bundled
  incident lookup. Incident metadata, deployment data, failure locations, and
  telemetry windows can be independently unavailable and later workflows can
  request only the evidence they need. The initial implementation is fake-only
  because existing OTLP/Grafana setup exports telemetry but does not provide a
  safe configured query boundary.
- **Invariant or failure behavior:** Provider-specific JSON/query text and raw
  stacks cannot enter the discriminated content union. Unavailable fixture data
  raises `FixtureNotFoundError`; it is never represented as invented empty
  evidence. Observed timestamps remain distinct from retrieval timestamps, and
  clock skew is not treated as invalid evidence.
- **Trade-off:** Multiple typed methods and models are more explicit than a
  generic `query()` function, but they make authorization, testing, future tool
  design, and provider adaptation safer. Deferring a live adapter postpones
  real-provider validation, but avoids inventing credentials and query semantics.
- **Validation evidence:** Focused incident/evidence/V2.3 regression tests,
  complete backend discovery, compilation, final teaching-comment revalidation,
  and `git diff --check` are recorded with this milestone's completion.
- **Unresolved question:** When a live provider is justified, should a deployment
  adapter share the same credentials and source lifecycle as incident telemetry,
  or become a separately configured provider behind the same port?

### 2026-08-17 - Add typed investigation tools without making the registry an executor

- **V2 milestone:** V2.5 Tool Abstraction and Registry.
- **Concept:** A connector or source is an application/provider capability;
  a tool is a smaller stable operation boundary designed for safe selection by
  deterministic code now and a planner later. `ToolRegistry` catalogs what
  exists. It does not decide what to request, authorize execution, or implement
  MCP.
- **Important syntax:** Pydantic `arbitrary_types_allowed` lets an immutable
  `ToolDefinition` carry input/output model classes while exposing the input
  model's JSON schema. `model_validator(mode="after")` keeps `ToolResult`
  outcome, evidence, and failure combinations consistent. A structural async
  `Protocol` keeps adapters independent from the future executor.
- **Implementation locations:** `app/tools/models.py` defines stable IDs,
  typed inputs, definitions, failures, and evidence results; `registry.py`
  provides deterministic register/get/list behavior; `adapters.py` connects
  seven tools to existing V2.3/V2.4/Jira capabilities; and
  `tests/unit/test_tool_registry.py` covers the boundary.
- **Design decision:** Keep registry metadata separate from handlers. This lets
  V2.6 deterministic selection and a future LLM planner share exactly the same
  tool surface while leaving timeouts, permissions, budgets, retries,
  idempotency, cancellation, and telemetry to a later runtime.
- **Invariant or failure behavior:** Tool IDs are stable and unique; listings
  are sorted; input validation is strict and happens before source execution;
  results contain normalized `Evidence`; invalid arguments, unknown tools,
  capability unavailability, source failure, and empty observation are not
  collapsed into one outcome. Provider payloads and generated prose cannot
  become tool output.
- **Trade-off:** Seven semantic tools are more deliberate than exposing every
  provider method or accepting `get_anything(query)`, but they require adapters
  and explicit schemas. Failure-location remains internal because it is not yet
  an independent selection action. The registry has no invocation helper, so a
  later runtime must compose definition lookup and adapter execution explicitly;
  that is intentional control rather than missing functionality.
- **Validation evidence:** `tests.unit.test_tool_registry` passed 14 tests;
  complete backend unittest discovery passed 297 tests with 6 PostgreSQL tests
  skipped because `TEST_DATABASE_URL` is absent; `.venv\\Scripts\\python.exe
  -m compileall -q app tests` and `git diff --check` passed after the final
  teaching-comment pass. Ruff was not run because no Ruff executable is
  installed in `services/api/.venv`.
- **Unresolved question:** When V2.6 chooses among tools, should it use one
  global registry with deterministic allowed-subset construction or separate
  per-workflow registries? Dynamic evidence-driven gating remains deferred.

### 2026-08-18 - Derive investigation relationships with ordinary deterministic code

- **V2 milestone:** V2.6 Deterministic Baseline and Fact Derivation.
- **Concept:** Evidence is a normalized observation; a Fact is a machine-readable
  relationship proven by joining observations. The baseline chooses fixed tool
  calls; focused derivation modules decide only what follows from collected evidence.
- **Implementation locations:** `investigations/baseline.py` owns dispatch,
  accumulation, branches, and partial failures. `fact_derivation/temporal.py`,
  `deployment.py`, and `code_change.py` own pure predicates. `models.py` adds
  relationship facts and `test_deterministic_baseline.py` covers the core flow.
- **Design decision:** The metadata registry stays separate from execution.
  `ToolInvoker` checks the registered definition before calling the existing
  V2.5 adapter. Failure location is an always-on subordinate source enrichment,
  not a dynamically selected hidden capability.
- **Invariant or failure behavior:** Each positive Fact preserves all evidence
  IDs used to prove it. Equal timestamps, mismatched paths/SHAs, absent patches,
  and zero new-line ranges produce no negative Fact. Failed tools become missing
  information; hypotheses stay empty and no LLM is called.
- **Trade-off:** Focused modules repeat small typed filters instead of introducing
  a generic rule engine. That is less abstract but keeps predicates and provenance
  easy to inspect and test.
- **Validation evidence:** 33 focused baseline, model, and tool tests passed;
  `python -m compileall -q app tests` passed. Full regression and final comment
  pass remain required.

### 2026-08-18 - Propose typed investigation work without granting execution authority

- **V2 milestone:** V2.7 Typed LLM Planner.
- **Concept:** Planning is a probabilistic proposal of evidence-gathering work;
  execution is a later deterministic decision. `PlannerInput` passes compact
  Facts, missing information, evidence summaries, and a caller-selected tool
  subset to `TypedLLMPlanner`, which returns a bounded `InvestigationPlan` but
  never invokes a V2.5 tool or changes V2.6 facts.
- **Important syntax:** A discriminated Pydantic union represents either
  `Literal` or `StepOutputRef` argument values; `tuple` fields plus frozen
  `ContractModel` contracts preserve stable proposal shape. `Protocol` lets the
  planner depend on `TypedLLMClient` instead of any provider SDK.
- **Implementation locations:** `investigations/planning/models.py` owns plan
  contracts; `prompt.py` performs deterministic context compression and tool
  ordering; `service.py` calls the provider-neutral boundary; and
  `explanations/models.py` plus existing provider adapters add `TypedLLMRequest`.
- **Design decision:** Keep control dependencies (`depends_on`) distinct from
  data dependencies (`StepOutputRef`). Explicit references make later replay,
  validation, and execution inspectable instead of requiring a runtime to infer
  which deployment or commit a vague intent meant.
- **Invariant or failure behavior:** Plans contain one to five steps, stable
  V2.5 tool IDs, no root-cause/fact/hypothesis fields, and no raw diff content.
  Provider failures, malformed outer responses, and invalid plan schema produce
  distinct planner failures. Full DAG/reference/tool-permission validation stays
  out of V2.7 and belongs to V2.8.
- **Trade-off:** A small explicit plan model is less expressive than a workflow
  DSL, but it avoids embedding scripts or hidden executor decisions in LLM
  output. Multi-step proposals give V2.8 meaningful graph work while a five-step
  bound limits speculative plans; dynamic replanning remains deferred.
- **Validation evidence:** Focused planner contracts, prompt construction, fake
  provider, and failure-boundary tests are in
  `tests/unit/test_typed_investigation_planner.py`; final full-suite and
  teaching-comment validation are recorded with milestone completion.
- **Unresolved question:** V2.8 must decide whether a data reference should
  always imply an explicit matching control dependency or whether it may add one
  deterministically during validation.

### 2026-08-18 — V2.8 deterministic plan validation

- **Concept:** A parsed Pydantic model is syntactically valid, but an executable
  graph also needs semantic validation. `PlanValidator` treats an LLM proposal
  like untrusted source code: it validates identity, tool allowlists, DAG edges,
  output references, and annotations before a future executor can receive it.
- **Important syntax:** `StrEnum` gives stable failure codes; `model_fields` and
  `rebuild_annotation()` expose Pydantic field contracts for static checking;
  Kahn's algorithm uses an in-degree map and heap ordered by original position
  to produce deterministic topological order.
- **Implementation and evidence:** `investigations/planning/validation.py`
  produces `PlanValidationResult`; `tools/models.py` adds metadata-only
  `plan_output_model` contracts; `test_investigation_plan_validator.py` covers
  acceptance, failures, type mismatch, atomic rejection, and determinism.
- **Decision:** ADR-022 selects explicit per-tool static output contracts rather
  than changing generic V2.5 `ToolResult`. This is enough to validate
  `s1.commit_sha -> get_commit.commit_sha` while postponing V2.9 projection.
- **Invariant and failure behavior:** A data reference must have a matching
  control dependency. Unknown tools, fields, types, and malformed literals
  become sanitized typed failures; any failure means no `ValidatedPlan`.
- **Trade-off:** Static contracts are deliberately narrower than JSONPath or a
  generic expression system. They require later executor projection work, but
  avoid arbitrary payload inspection and keep validation predictable.
- **Unresolved question:** V2.9 must define how observed evidence becomes the
  declared static output fields without leaking provider-specific payloads.

### 2026-08-19 — Interpret a validated investigation DAG within a fixed budget

- **V2 milestones:** V2.9 Agent Execution Loop and V2.10 Minimal Execution Budgets.
- **Concept and syntax:** `AgentExecutor` in `investigations/execution.py` is an
  interpreter: `ValidatedPlan` is its checked program, `Literal` and
  `StepOutputRef` are operands, and `ToolInvoker` is the controlled call boundary.
  `StrEnum` supplies stable step/block/termination codes; `model_copy(update=...)`
  advances the `BudgetState` counter.
- **Implementation and evidence:** Runtime projections read only normalized
  `Evidence.content` fields declared by V2.8 output contracts, then
  `ToolDefinition.validate_arguments` creates the destination input before V2.5
  invocation. `tests/unit/test_agent_execution.py` covers chains, branches,
  runtime references, typed inputs, full-set derivation, dedupe, partial failure,
  and budget accounting.
- **Decision:** Recompute Facts from all accumulated Evidence after a genuine
  evidence-ID addition. Old deployment evidence plus new incident evidence can
  form a temporal fact, so newest-only derivation is wrong. Bounded plans make
  full recomputation simpler than an incremental rule graph.
- **Invariant and failure behavior:** `failed` means a call was attempted and
  returned typed failure; `blocked` means it was not invoked due to dependency,
  output, or budget policy. Independent branches continue. Failed attempts use
  budget; blocked steps do not; exhaustion preserves collected Evidence/Facts.
- **Trade-off and unresolved question:** Sequential execution makes ordering and
  accounting deterministic but leaves branch concurrency for later atomic budget
  reservation work. Dynamic replanning, retries, and full agent telemetry remain
  deferred.
