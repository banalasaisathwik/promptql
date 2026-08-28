# Deployment (public demo: Vercel + Render + Neon)

This describes the one supported public-demo topology: `apps/web` on Vercel,
`services/api` on Render's free tier, and the existing Neon PostgreSQL
project. It assumes local development already works per [README.md](README.md).

## Render (backend)

### Required environment variables

Set these by hand in Render's dashboard. **Do not copy `services/api/.env`
into Render.** That file is a local development file and, by design, may
carry live-provider keys (e.g. `PROMPTQL_LLM_PROVIDER=groq` plus a real
`GROQ_API_KEY`) sitting alongside connector settings that are separately
`fake`. Copying it wholesale is the one realistic way this deployment could
start making live, paid calls on a public visitor's behalf.

| Variable | Value | Why |
| --- | --- | --- |
| `DATABASE_URL` | Neon **pooled** connection string, with `sslmode=require` (or stricter) | The only variable required at boot; `DatabaseSettings.from_environment()` fails startup without it. |

### Leave unset, or set explicitly to `fake`

Do not set these to anything else on a public deployment:

```text
PROMPTQL_LLM_PROVIDER=fake
PROMPTQL_GITHUB_CONNECTOR=fake
PROMPTQL_JIRA_CONNECTOR=fake
PROMPTQL_SENTRY_CONNECTOR=fake
```

Each defaults to `fake` when unset, so an empty Render environment is
already safe. Setting them explicitly is a belt-and-suspenders step against
a future accidental default change, not a requirement. There is no
request-level way for a visitor to override provider or connector selection
— each is read once from the environment at process startup
(`app/config.py`) and baked into a process-lifetime client stored on
`app.state`.

### Health check

Configure Render's health check path as `GET /health`. Startup runs a
database-readiness check (`verify_database_ready`) before the app accepts
any request, including the health check itself, so the first request after
a free-tier cold start (the instance spins down after ~15 minutes idle) can
take up to roughly the same time as a fresh boot. Give the health check a
generous timeout rather than assuming a sub-second response.

## Vercel (frontend)

`apps/web/vercel.json` rewrites `/v1/:path*` to the Render backend, so the
browser only ever talks to the Vercel origin — no CORS configuration is
needed or added, preserving the same-origin design documented in
`apps/web/vite.config.ts`.

Before deploying, edit the placeholder destination in `apps/web/vercel.json`
to the real Render URL once Render assigns one (e.g.
`https://promptql-api.onrender.com`):

```json
{
  "rewrites": [
    {
      "source": "/v1/:path*",
      "destination": "https://<your-render-service>.onrender.com/v1/:path*"
    }
  ]
}
```

No change to `apps/web/src/features/inspection/api.ts` is needed — it
already calls relative `/v1/...` paths.

## What's already safe by default

- Rate limiting: `PerIpRateLimitMiddleware`
  (`services/api/app/api/v1/rate_limit.py`) caps requests per client IP to
  the two LLM-touching/DB-writing endpoints
  (`POST /v1/investigations`, `POST /v1/investigations/extract-grounding`),
  returning `429` once exceeded. This is in-memory and per-process — it
  resets on redeploy and does not coordinate across multiple instances,
  which is an acceptable trade-off at Render free-tier (single instance)
  demo scale.
- The demo button ("Run demo investigation") submits a fixed, static
  payload matching the fake-mode fixtures already used in
  `services/api/app/evals/investigations/cases.py` — it does not accept or
  forward free-text visitor input to that payload.
