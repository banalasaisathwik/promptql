# Learning log

This log stores concise, reusable engineering lessons supported by repository
evidence. It is not a conversation transcript, diary, or substitute for an ADR.

## Entry template

### YYYY-MM-DD — Lesson title

- **Concept:** The engineering idea.
- **Implementation location:** Files, functions, tests, or commands providing evidence.
- **Misconception corrected:** The prior assumption and more accurate model.
- **Trade-off learned:** The concrete benefit, cost, and relevant conditions.
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
