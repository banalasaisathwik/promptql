# Execution plan: OpenRouter deterministic task model routing

- Status: Completed
- Related milestone: V2 investigation runtime support

## Objective

Add OpenRouter through the existing OpenAI-compatible provider boundary and route
the existing planning and hypothesis-generation workloads to configured models
deterministically.

## Implemented scope

- `LLMTask` and `ModelPolicy` resolve task-specific settings with an explicit
  default-model fallback.
- OpenRouter reuses the existing Chat Completions structured-output adapter and
  fixed compatibility URL, with SDK retries disabled.
- Application assembly constructs separate planner and hypothesis clients; the
  domain planner, generator, validators, and adaptive runtime remain unchanged.
- The planner's serialized `value_kind` contract uses an explicit discriminator,
  while numeric literals expose one provider-facing `number` branch rather than
  overlapping `integer` and `number` branches. Pydantic remains the local
  validation authority.
- Real `PlannerInput` now includes the unchanged typed investigation request and
  the allowed tools' exact input/output schemas. The planner can therefore copy
  known fixture identifiers and reference only fields the validator accepts.
- Planner and hypothesis failures retain only allowlisted provider status,
  category/code, sanitized fixed messages, and failed-generation presence/length.

## Deferred

- Code diagnosis execution, semantic/automatic routing, model fallbacks, and
  Langfuse.

## Provider-boundary diagnosis

- Safe resolution selected OpenRouter and `openai/gpt-oss-120b` for both planning
  and hypothesis generation without exposing the API key.
- Plain Chat Completions and a tiny typed schema passed.
- Groq first rejected the ambiguous numeric schema, then accepted the corrected
  schema. Subsequent live samples separated valid plans from account rate limits.
- The isolated planner passed while the real workflow failed because the smaller
  diagnostic input omitted request values and exact tool schemas. Live diagnostics
  proved schema-valid plans were inventing fields/values that `PlanValidator` or
  the evidence sources could not accept.
- A stale API process retained live GitHub/Jira connector settings while the UI
  submitted the fake `octo-org/analytics` preset. A clean restart with fake
  connectors removed the `not_found` tool failures.
- With the 120B reasoning model, a 30-second/2048-token OpenRouter allowance still
  produced `length_finish_reason` in planning round 3. The local run configuration
  now uses the supported 120-second/4096-token bounds; no retry was added.

## Validation

Re-run the direct planner and hypothesis diagnostics, focused offline tests,
complete backend discovery, and the comment-only teaching pass.

## Completion

The safe configuration, real Groq/OpenRouter typed boundaries, realistic planner,
and realistic hypothesis generation all passed without exposing credentials or
raw provider payloads. The final direct HTTP proof used
`POST /v1/investigations` followed by `GET /v1/runs/{id}`. Run
`6681341f-9c73-4155-a17b-5478b297209d` completed with three planning rounds,
seven tool calls, seven Evidence records, five Facts, one accepted hypothesis,
and no missing information. Its grounded result states that changes associated
with `services/checkout.py` may have contributed to the incident.

The final focused provider/workflow suite passed 65 tests. Complete backend discovery
passed 374 tests with six PostgreSQL tests skipped because `TEST_DATABASE_URL`
was unset. Python compilation and `git diff --check` passed after the final
comment-only teaching pass. Ruff was not available in the project environment,
so no Ruff result is claimed.
