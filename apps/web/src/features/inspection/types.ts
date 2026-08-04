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
export type BlockerState = 'blocked' | 'not_blocked' | 'unknown'

export interface GitHubUser {
  login: string
}

export interface RequiredCheck {
  name: string
  status: CheckStatus
}

export interface GitHubPullRequest {
  pr_number: number
  title: string
  url: string
  head_branch: string
  base_branch: string
  state: PullRequestState
  is_draft: boolean
  mergeability: Mergeability
  required_checks: RequiredCheck[]
  required_checks_known: boolean
  approvals: GitHubUser[]
  required_approval_count: number | null
  reviews_known: boolean
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
  status_id: string | null
  status_name: string | null
  is_resolved: boolean | null
}

export type MergeReadinessDecision = 'ready' | 'blocked' | 'unknown'

export type PolicyReasonCode =
  | 'ready'
  | 'pr_is_draft'
  | 'pr_closed_unmerged'
  | 'merge_conflict'
  | 'ci_check_failed'
  | 'ci_check_pending'
  | 'approval_missing'
  | 'changes_requested'
  | 'jira_link_missing'
  | 'jira_not_complete'
  | 'jira_blocker_present'
  | 'evidence_unavailable'

export type PendingActionCode =
  | 'mark_pr_ready'
  | 'reopen_pr'
  | 'resolve_merge_conflict'
  | 'fix_ci_check'
  | 'wait_for_ci_check'
  | 'get_required_approval'
  | 'address_requested_changes'
  | 'link_jira_issue'
  | 'complete_jira_issue'
  | 'clear_jira_blocker'
  | 'retry_evidence'

export type EvidenceSource = 'github' | 'jira'

export interface EvidenceReference {
  reference_id: string
  source: EvidenceSource
  field: string
  value: string | boolean | number | null
}

export interface PolicyFinding {
  reason_code: PolicyReasonCode
  message: string
  evidence_reference_ids: string[]
}

export interface PendingAction {
  action_code: PendingActionCode
  reason_code: PolicyReasonCode
  message: string
}

export interface MergeReadinessResult {
  decision: MergeReadinessDecision
  summary: string
  reason_code: PolicyReasonCode
  blockers: PolicyFinding[]
  pending_actions: PendingAction[]
  missing_information: PolicyFinding[]
  evidence_references: EvidenceReference[]
}

export type RuntimeStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type WorkflowStepName =
  | 'fetch_github_facts'
  | 'fetch_jira_facts'
  | 'evaluate_merge_readiness'

export type RuntimeErrorCode =
  | 'connector_execution_failed'
  | 'policy_execution_failed'
  | 'fixture_not_found'

export interface RuntimeErrorInfo {
  code: RuntimeErrorCode
  message: string
}

export interface RuntimeStep {
  step_id: string
  name: WorkflowStepName
  status: RuntimeStatus
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  attempt: number
  error: RuntimeErrorInfo | null
}

export interface PullRequestMergeReadiness {
  run_id: string
  workflow_name: string
  workflow_version: string
  status: 'completed'
  started_at: string
  completed_at: string
  steps: RuntimeStep[]
  error: null
  result: MergeReadinessResult
  request: ConnectorRequest
  github: GitHubPullRequest | null
  jira: JiraIssue | null
}
