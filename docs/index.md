# Documentation index

This system separates current facts, historical decisions, and work in progress
so plans are not mistaken for implemented behavior.

## Sources of truth

- Product scope and non-goals: [PRODUCT.md](PRODUCT.md)
- Current architecture and ownership: [ARCHITECTURE.md](ARCHITECTURE.md)
- Testing conventions and capability: [TESTING.md](TESTING.md)
- Historical decisions: [decisions/index.md](decisions/index.md)
- Current work: [tasks/active](tasks/active/) and [plans/active](plans/active/)

## Document map

| Document | Purpose | Read when |
| --- | --- | --- |
| [../README.md](../README.md) | Verified setup and repository overview | Starting locally |
| [PRODUCT.md](PRODUCT.md) | Product problem, version scope, and non-goals | Evaluating feature scope |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture that exists now | Changing a boundary or data flow |
| [TESTING.md](TESTING.md) | Present and planned testing layers | Adding or validating behavior |
| [agent/PLAYBOOK.md](agent/PLAYBOOK.md) | Agent workflow and artifact rules | Beginning non-trivial work |
| [decisions/index.md](decisions/index.md) | ADR policy and register | Reviewing durable decisions |
| [decisions/ADR-TEMPLATE.md](decisions/ADR-TEMPLATE.md) | ADR structure | Recording an accepted decision |
| [tasks/TASK-TEMPLATE.md](tasks/TASK-TEMPLATE.md) | One bounded task | Tracking a small implementation |
| [plans/EXEC-PLAN-TEMPLATE.md](plans/EXEC-PLAN-TEMPLATE.md) | Staged work plan | Coordinating cross-layer, high-risk, or multi-session work |
| [learning/LEARNING-LOG.md](learning/LEARNING-LOG.md) | Repository-grounded lessons | Capturing reusable learning |

Completed records belong in [tasks/completed](tasks/completed/) and
[plans/completed](plans/completed/).

## Normal agent reading order

1. Read the closest `AGENTS.md`.
2. Read this index.
3. Read relevant product, architecture, and testing docs.
4. Read applicable ADRs and active work records.
5. Inspect nearby source, tests, manifests, and the Git diff.

## Update rules

- Update product scope, current architecture, and testing commands only when
  their underlying facts change.
- Add or supersede an ADR for a resolved durable decision; never rewrite
  accepted history.
- Move work records from active to completed when their validation finishes.
- Label future capabilities as planned.
- Publish commands only after verifying them.
