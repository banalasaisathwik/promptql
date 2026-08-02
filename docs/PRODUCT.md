# Product

PromptQL is an enterprise investigation and analytics agent inspired by
PromptQL-like systems. It is intended to help users ask business questions,
inspect supporting evidence, and iteratively investigate data across approved
enterprise sources. The problem is not merely prose generation: users need to
know what data informed a conclusion, where uncertainty remains, and whether
access boundaries were respected.

## V0: foundations

V0 establishes:

- the repository and package-management boundaries;
- a Vite, React, and TypeScript frontend foundation;
- a FastAPI backend foundation;
- documentation and decision-record practices;
- testing conventions, where tooling may still be unconfigured; and
- an agent-development workflow that supports review and learning.

V0 does **not** implement the complete agent runtime. The current UI loads demo
fixture choices, submits a typed connector request, and displays the
deterministic merge-readiness decision, findings, actions, missing information,
and evidence returned by the V1 API.

## Later directions

Later versions may introduce investigation workflows, governed connectors,
persistent state, model and prompt operations, evidence-aware answers, and
evaluation infrastructure. These are directions, not current capabilities, and
each architectural choice requires separate resolution.

## V0 non-goals

- A production-ready autonomous agent runtime
- Database, queue, cache, or cloud deployment selection
- Enterprise identity, authorization, or tenant isolation
- Live enterprise data connectors
- Model-provider integration or prompt management
- Automated evaluation pipelines
- Unsupported claims of production readiness, scale, or security
