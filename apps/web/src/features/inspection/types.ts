/**
 * Shared TypeScript shapes for the connector-inspection feature.
 *
 * This file contains data definitions only. It does not validate, fetch, or
 * render anything. Keeping types separate lets a beginner answer “what data
 * exists?” without reading network and React code at the same time.
 */

// These names intentionally match the backend's snake_case JSON fields. That
// removes a conversion layer that could drift away from the Pydantic contract.
export interface ConnectorRequest {
  repository_owner: string
  repository_name: string
  pr_number: number
}

// HTML inputs produce strings, even for numeric-looking values. The draft type
// therefore represents what the user can type; ConnectorRequest represents only
// data that has successfully passed validation.
export interface ConnectorRequestDraft {
  repository_owner: string
  repository_name: string
  pr_number: string
}

// `keyof ConnectorRequestDraft` derives the three legal field names. `Partial`
// means each error is optional because valid fields have no message.
export type ConnectorRequestErrors = Partial<
  Record<keyof ConnectorRequestDraft, string>
>

export type ConnectorRequestResult =
  | { ok: true; request: ConnectorRequest }
  | { ok: false; errors: ConnectorRequestErrors }

export interface FixtureScenario {
  id: string
  label: string
  request: ConnectorRequest
}

// String unions mirror backend enums and provide editor autocomplete without
// introducing runtime JavaScript objects.
export type PullRequestState = 'open' | 'closed' | 'merged'
export type Mergeability = 'mergeable' | 'conflicting' | 'unknown'
export type CheckStatus = 'pending' | 'passed' | 'failed'
export type JiraIssueStatus = 'to_do' | 'in_progress' | 'done'
export type BlockerState = 'blocked' | 'not_blocked'

export interface GitHubUser {
  login: string
}

export interface RequiredCheck {
  name: string
  status: CheckStatus
}

export interface GitHubPullRequest {
  state: PullRequestState
  is_draft: boolean
  mergeability: Mergeability
  required_checks: RequiredCheck[]
  approvals: GitHubUser[]
  changes_requested: boolean
  author: GitHubUser
  assignees: GitHubUser[]
  requested_reviewers: GitHubUser[]
  linked_jira_key: string | null
}

export interface JiraAssignee {
  account_id: string
  display_name: string
}

export interface JiraIssue {
  issue_key: string
  status: JiraIssueStatus
  blocker_state: BlockerState
  assignee: JiraAssignee | null
}

export interface PullRequestInspection {
  request: ConnectorRequest
  github: GitHubPullRequest
  jira: JiraIssue
}
