# ADR-021: Focused GitHub code-evidence source

- Status: Accepted
- Date: 2026-08-17
- Owners: Repository owner
- Supersedes: None
- Superseded by: None

## Context

V1 `GitHubConnector` returns merge-readiness facts for one pull request. V2.3
needs a read-only provider boundary for commit metadata, investigation-oriented
pull-request metadata, changed files, and bounded diff hunks. Adding those
operations to the V1 protocol would make existing merge-readiness fakes and
callers depend on capabilities they do not use.

GitHub REST responses are untrusted provider data. They can omit patch content,
paginate changed files, contain unsupported status values, exceed local safety
bounds, or fail with provider-controlled error bodies. The investigation domain
must receive only validated V2.2 `Evidence`, never raw JSON or HTTP objects.

## Decision drivers

- Preserve the stable V1 merge-readiness protocol and behavior.
- Keep provider response schemas and credentials outside the V2 domain.
- Make pagination truncation distinct from an empty complete result.
- Keep patch content typed and bounded without adding a diff dependency.
- Reuse existing authentication, sanitized failures, configuration, and telemetry.
- Keep provider capability separate from future planner-visible tools.

## Options considered

### Option A: Extend the V1 GitHubConnector protocol

One protocol would expose merge-readiness and code-investigation methods. A
single HTTP class could reuse internals directly, but every fake and caller
would see an unrelated larger interface. Future code-evidence evolution would
increase the blast radius of the stable V1 boundary.

### Option B: Add a focused GitHubCodeEvidenceSource protocol

A separate protocol exposes only commit, pull-request, and changed-file
evidence operations. Dedicated HTTP and fake implementations reuse shared
settings and failure conventions while returning V2.2 evidence contracts. This
adds a small amount of adapter code but satisfies Interface Segregation and
keeps V1 unchanged.

### Option C: Expose generic GitHub JSON through one provider client

A generic client would be easy to extend, but it would move schema validation,
normalization, redaction, pagination completeness, and diff parsing into every
consumer. It would also invite raw provider dictionaries into the domain.

## Repository owner reasoning

The V2.3 brief prefers a focused code-evidence capability when extending the
existing connector would create a large unrelated interface. It requires raw
GitHub data to remain inside the adapter and explicitly distinguishes provider
capability from a planner-visible tool.

## Reasoning review

Option B best preserves the current use-case boundary. Sharing configuration
and sanitized errors avoids rebuilding established infrastructure without
making protocol consumers depend on one another. A shared protocol would only
be preferable if both workflows later require the same stable operations.

## Decision

Introduce `GitHubCodeEvidenceSource` with three read-only operations:

```text
get_commit_evidence
get_pull_request_evidence
get_changed_file_evidence
```

Use dedicated fake and HTTP implementations. The HTTP adapter validates private
response models, normalizes stable fields, parses bounded unified-diff hunks,
and constructs investigation `Evidence` directly. Reuse `GitHubSettings`, the
application-scoped HTTP client, sanitized GitHub errors, and bounded telemetry.

Pagination exhaustion and locally bounded patch truncation raise an explicit
incomplete-result error; they never return partial evidence as complete.

## Consequences

- V1 callers and fakes remain unchanged.
- V2 callers cannot receive raw dictionaries or HTTP response objects.
- One pull-request file call returns file evidence followed by its hunk evidence
  in stable provider order.
- Missing GitHub patch text is explicit on file evidence and is not an error.
- Malformed patch syntax is an invalid provider response; detected truncation or
  safety-bound exhaustion is an incomplete provider result.
- A new evidence/content type requires explicit domain, adapter, and test updates.
- No production dependency, persistence migration, API, deployment, or LLM cost
  is introduced.

## Invariants

- Only normalized V2.2 `Evidence` crosses the provider boundary.
- Repository identifiers, SHAs, PR numbers, file paths, and counts are validated.
- Evidence source, kind, provenance, and typed content agree.
- Patch absence differs from an empty patch and from incomplete parsing.
- Hunk old/new ranges agree with the normalized line kinds.
- Pagination preserves provider order and never silently truncates.
- Telemetry contains bounded operation/result metadata, never repository data or code.
- The capability is not registered as a planner tool.

## Validation

Focused unit tests cover response normalization, failure taxonomy, pagination,
diff parsing, evidence validation, fakes, and factory selection. Existing V1
GitHub tests, V2.1/V2.2 tests, compilation, full backend discovery, and diff
hygiene must pass before this ADR is considered implemented.

## Reconsideration triggers

Revisit the protocol shape when a real deterministic investigation workflow
reveals that the three operations should be composed differently. Revisit patch
bounds when measured GitHub responses show legitimate hunks exceed them.
Commit-to-PR association remains deferred until a concrete workflow requires it.
