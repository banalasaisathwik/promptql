# PromptQL

PromptQL is an early-stage enterprise investigation and analytics agent inspired
by PromptQL-like systems. This repository currently provides the frontend,
backend, documentation, testing, and agent-development foundations; it does not
yet contain the complete agent runtime.

## Repository layout

| Path | Purpose |
| --- | --- |
| `apps/web` | Vite, React, and TypeScript browser application |
| `services/api` | FastAPI Python API managed with `uv` |
| `packages` | Reserved for reusable TypeScript packages |
| `docs` | Product, architecture, testing, decision, task, plan, and learning documentation |
| `infra` | Reserved for infrastructure configuration |
| `scripts` | Reserved for repository automation |

## Prerequisites

- Bun
- Python 3.13 or newer
- uv
- Git
- A managed Neon PostgreSQL project for durable runtime execution

## Setup and run

From the repository root:

```bash
bun install
bun run dev:web
```

From `services/api`:

```bash
uv sync
```

Use `.env.example` as a reference and set these values in the shell environment
that runs Alembic and FastAPI:

```text
DATABASE_URL=<pooled Neon PostgreSQL URL>
DATABASE_MIGRATION_URL=<direct Neon PostgreSQL URL>
```

GitHub uses deterministic fixtures by default:

```text
PROMPTQL_GITHUB_CONNECTOR=fake
```

To run the read-only live connector, set `PROMPTQL_GITHUB_CONNECTOR=github`
and provide a local `GITHUB_TOKEN`. Do not commit the token. Live mode never
falls back to fixture data after a GitHub failure.

Jira is selected independently and also defaults to fixtures:

```text
PROMPTQL_JIRA_CONNECTOR=fake
```

Live Jira Cloud mode requires the HTTPS site URL, Atlassian account email, and
a revocable API token—not the account password:

```text
PROMPTQL_JIRA_CONNECTOR=jira
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=<local account email>
JIRA_API_TOKEN=<local secret>
JIRA_REQUEST_TIMEOUT_SECONDS=10
```

Explanation generation is also selected independently. The deterministic fake
is the credential-free default for local development and every automated test:

```text
PROMPTQL_LLM_PROVIDER=fake
```

OpenAI mode uses the Responses API and requires a local API key plus an
explicit Structured Output-capable model. Never commit the key:

```text
PROMPTQL_LLM_PROVIDER=openai
OPENAI_API_KEY=<local secret>
OPENAI_MODEL=<approved model ID>
OPENAI_REQUEST_TIMEOUT_SECONDS=30
OPENAI_MAX_OUTPUT_TOKENS=512
```

Gemini mode still uses the installed OpenAI SDK, but the application fixes the
SDK base URL to Google's OpenAI-compatible endpoint and uses Chat Completions
structured parsing. Use Gemini-specific names so a Google key cannot be
mistaken for an OpenAI key:

```text
PROMPTQL_LLM_PROVIDER=gemini
GEMINI_API_KEY=<local Gemini API key>
GEMINI_MODEL=gemini-2.5-flash
GEMINI_REQUEST_TIMEOUT_SECONDS=30
GEMINI_MAX_OUTPUT_TOKENS=512
```

`GEMINI_API_KEY` must contain a Gemini API key created in Google AI Studio. It
is not an OpenAI key, Google OAuth access token, project ID, or service-account
JSON value. If Google rejects the key, the terminal emits a safe event like:

```json
{"event":"llm.explanation.failed","failure_category":"authentication","llm_provider":"gemini"}
```

The real log also contains a timestamp and, when available, trace/span IDs. It
never contains the key, raw provider message, prompt, output, headers, or URL.
This structured application event is emitted even when trace/metric exporters
are disabled; the telemetry flags control exporters, not error sanitization.

Both real adapters send only the minimized policy decision/reason/action
contract, disable SDK retries, discard generated prose, and validate codes
before rendering backend-owned text. OpenAI additionally sets `store=False` on
its Responses request. Provider failure does not fall back to the fake and does
not change the stored policy run.

Telemetry is safe and disabled by default. To inspect spans and metrics locally
without an external service, opt into console exporters:

```text
PROMPTQL_TELEMETRY_ENABLED=true
PROMPTQL_TELEMETRY_CONSOLE_ENABLED=true
OTEL_SERVICE_NAME=promptql-api
```

For Grafana Cloud, keep the console exporter disabled and set the provider's
OTLP base URL and encoded authorization header. Use real values only in your
local environment or secret manager:

```text
PROMPTQL_TELEMETRY_ENABLED=true
PROMPTQL_TELEMETRY_CONSOLE_ENABLED=false
OTEL_SERVICE_NAME=promptql-api
OTEL_EXPORTER_OTLP_ENDPOINT=<https OTLP base URL ending in /otlp>
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic%20<base64-instance-id-and-token>
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

The application appends `/v1/traces` and `/v1/metrics` to that base endpoint.
Do not commit `.env`, API tokens, or rendered authorization headers.

Apply migrations explicitly, then start the API:

```bash
uv run --env-file .env alembic upgrade head
uv run --env-file .env python -m uvicorn app.main:app --reload
```

The repository does not yet provide one command that starts both applications.
The API never creates tables or runs migrations automatically at startup.

Run credential-free backend tests with:

```bash
uv run python -m unittest discover -s tests -v
```

PostgreSQL integration tests require a dedicated test branch and the explicit
environment variables documented in [TESTING.md](docs/TESTING.md).

## Manual live explanation-provider smoke test

Ordinary tests never contact OpenAI or Gemini. Perform this only after placing
one provider's API key in `services/api/.env` and explicitly choosing its
model. Do not print the key, prompt, raw output, request ID, headers, or raw
exception details.

1. Keep both connectors deterministic so this smoke test exercises only the
   selected provider boundary. The following example selects Gemini:

   ```text
   PROMPTQL_GITHUB_CONNECTOR=fake
   PROMPTQL_JIRA_CONNECTOR=fake
   PROMPTQL_LLM_PROVIDER=gemini
   GEMINI_API_KEY=<local Gemini API key>
   GEMINI_MODEL=gemini-2.5-flash
   GEMINI_REQUEST_TIMEOUT_SECONDS=30
   GEMINI_MAX_OUTPUT_TOKENS=512
   ```

2. From `services/api`, apply the existing migration and start FastAPI:

   ```powershell
   uv run --env-file .env alembic upgrade head
   uv run --env-file .env python -m uvicorn app.main:app --reload
   ```

3. In another PowerShell window, submit the merge-ready fixture:

   ```powershell
   $requestBody = @{
       repository_owner = "acme"
       repository_name = "analytics"
       pr_number = 1
   } | ConvertTo-Json

   $response = Invoke-RestMethod `
       -Method Post `
       -Uri "http://127.0.0.1:8000/v1/pull-request-merge-readiness" `
       -ContentType "application/json" `
       -Body $requestBody

   $response.result.decision
   $response.explanation
   $response.explanation_error
   ```

   Verify the authoritative decision remains `ready`, the explanation uses the
   existing deterministic wording, and `explanation_error` is empty. If the
   provider fails, the policy result must remain present and the response must
   contain only the existing sanitized explanation error.

4. If telemetry is enabled, verify the explanation span contains only bounded
   provider/result/failure attributes and input/output/total token counts. A
   later `GET /v1/runs/{run_id}` currently generates another read-time
   explanation and can incur another provider call.

5. Stop FastAPI and restore deterministic local development:

   ```text
   PROMPTQL_LLM_PROVIDER=fake
   GEMINI_API_KEY=
   GEMINI_MODEL=
   OPENAI_API_KEY=
   OPENAI_MODEL=
   ```

## Manual live GitHub smoke test

This procedure is manual because ordinary tests never contact GitHub.

1. In the shell that will start FastAPI, set the database values above and:

   ```powershell
   $env:PROMPTQL_GITHUB_CONNECTOR = "github"
   $env:PROMPTQL_JIRA_CONNECTOR = "fake"
   $env:GITHUB_TOKEN = "<local fine-grained token>"
   $env:GITHUB_API_BASE_URL = "https://api.github.com"
   $env:GITHUB_REQUEST_TIMEOUT_SECONDS = "10"
   ```

2. From `services/api`, apply migrations and start the API:

   ```powershell
   uv run --env-file .env alembic upgrade head
   uv run --env-file .env python -m uvicorn app.main:app --reload
   ```

3. In a second PowerShell window, inspect one repository and pull request that
   the token may read:

   ```powershell
   $requestBody = @{
       repository_owner = "<owner>"
       repository_name = "<repository>"
       pr_number = 123
   } | ConvertTo-Json

   $run = Invoke-RestMethod `
       -Method Post `
       -Uri "http://127.0.0.1:8000/v1/pull-request-merge-readiness" `
       -ContentType "application/json" `
       -Body $requestBody

   $run
   Invoke-RestMethod "http://127.0.0.1:8000/v1/runs/$($run.run_id)"
   ```

   Verify that authentication and repository access succeed, GitHub fields are
   normalized and persisted, and connector spans identify GitHub `source=live`
   and Jira `source=fake` when telemetry is enabled.

4. Stop FastAPI and switch back to deterministic fixtures:

   ```powershell
   $env:PROMPTQL_GITHUB_CONNECTOR = "fake"
   $env:PROMPTQL_JIRA_CONNECTOR = "fake"
   Remove-Item Env:GITHUB_TOKEN -ErrorAction SilentlyContinue
   ```

## Manual live GitHub plus Jira Cloud smoke test

Ordinary tests never contact Atlassian. Create one harmless Jira Cloud issue,
generate a revocable Atlassian API token, and place the issue key in a readable
GitHub PR title, body, or branch. Password authentication is not supported.

1. Put local secrets only in `services/api/.env`:

   ```text
   PROMPTQL_GITHUB_CONNECTOR=github
   GITHUB_TOKEN=<local secret>
   GITHUB_API_BASE_URL=https://api.github.com

   PROMPTQL_JIRA_CONNECTOR=jira
   JIRA_BASE_URL=https://your-domain.atlassian.net
   JIRA_EMAIL=<Atlassian account email>
   JIRA_API_TOKEN=<local secret>
   JIRA_REQUEST_TIMEOUT_SECONDS=10
   ```

2. Apply the existing runtime migration and start FastAPI:

   ```powershell
   cd C:\projects\promptql\services\api
   uv run --env-file .env alembic upgrade head
   uv run --env-file .env python -m uvicorn app.main:app --reload
   ```

3. Submit the real PR whose GitHub metadata contains the real Jira key:

   ```powershell
   $requestBody = @{
       repository_owner = "<real owner>"
       repository_name = "<real repository>"
       pr_number = 123
   } | ConvertTo-Json

   $run = Invoke-RestMethod `
       -Method Post `
       -Uri "http://127.0.0.1:8000/v1/pull-request-merge-readiness" `
       -ContentType "application/json" `
       -Body $requestBody

   $run
   Invoke-RestMethod "http://127.0.0.1:8000/v1/runs/$($run.run_id)"
   ```

4. Verify three ordered completed steps, normalized Jira category/status
   evidence, durable retrieval, and `github=live` plus `jira=live` span sources.
   Inspect logs/spans to ensure no email, token, Basic header, URL, issue key, or
   raw response appears. A non-done category is a verified blocker. A done
   category removes that blocker, but the result remains `unknown` while the
   standard Jira API cannot prove the site-specific blocker state.

5. If practical, move only the harmless test issue between an in-progress and
   done-category status and repeat the request. Do not manufacture error states.

6. Stop the API and restore deterministic development:

   ```text
   PROMPTQL_GITHUB_CONNECTOR=fake
   PROMPTQL_JIRA_CONNECTOR=fake
   GITHUB_TOKEN=
   JIRA_EMAIL=
   JIRA_API_TOKEN=
   ```

Create/revoke Atlassian API tokens through Atlassian account security. Basic
email/token authentication is intentionally limited to this single-user V1;
OAuth or an Atlassian app is required before multi-user deployment.

Start with the [documentation index](docs/index.md) before making changes.
