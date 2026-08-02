/**
 * Runtime guards for JSON received from the backend.
 *
 * TypeScript interfaces disappear when code is compiled. Network data is
 * therefore `unknown` until these functions prove every required field. This is
 * the browser equivalent of validating external input with Pydantic.
 */

import { ConnectorApiError } from './apiError'
import type {
  ConnectorRequest,
  EvidenceReference,
  FixtureScenario,
  GitHubPullRequest,
  GitHubUser,
  JiraIssue,
  MergeReadinessResult,
  PendingAction,
  PolicyFinding,
  PullRequestMergeReadiness,
  RequiredCheck,
} from './types'


const POLICY_REASON_CODES = [
  'ready',
  'pr_is_draft',
  'pr_closed_unmerged',
  'merge_conflict',
  'ci_check_failed',
  'ci_check_pending',
  'approval_missing',
  'changes_requested',
  'jira_link_missing',
  'jira_not_complete',
  'jira_blocker_present',
  'evidence_unavailable',
] as const

const PENDING_ACTION_CODES = [
  'mark_pr_ready',
  'reopen_pr',
  'resolve_merge_conflict',
  'fix_ci_check',
  'wait_for_ci_check',
  'get_required_approval',
  'address_requested_changes',
  'link_jira_issue',
  'complete_jira_issue',
  'clear_jira_blocker',
  'retry_evidence',
] as const


// A JavaScript array is also an object, so the Array check prevents accidentally
// accepting an array where a keyed JSON object is required.
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}


function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}


function isOneOf<T extends string>(
  value: unknown,
  allowed: readonly T[],
): value is T {
  return typeof value === 'string' && allowed.includes(value as T)
}


function isConnectorRequest(value: unknown): value is ConnectorRequest {
  return (
    isRecord(value) &&
    isNonEmptyString(value.repository_owner) &&
    isNonEmptyString(value.repository_name) &&
    Number.isSafeInteger(value.pr_number) &&
    Number(value.pr_number) > 0
  )
}


function isGitHubUser(value: unknown): value is GitHubUser {
  return isRecord(value) && isNonEmptyString(value.login)
}


function isRequiredCheck(value: unknown): value is RequiredCheck {
  return (
    isRecord(value) &&
    isNonEmptyString(value.name) &&
    isOneOf(value.status, ['pending', 'passed', 'failed'])
  )
}


function isGitHubPullRequest(value: unknown): value is GitHubPullRequest {
  return (
    isRecord(value) &&
    isOneOf(value.state, ['open', 'closed', 'merged']) &&
    typeof value.is_draft === 'boolean' &&
    isOneOf(value.mergeability, ['mergeable', 'conflicting', 'unknown']) &&
    Array.isArray(value.required_checks) &&
    value.required_checks.every(isRequiredCheck) &&
    Array.isArray(value.approvals) &&
    value.approvals.every(isGitHubUser) &&
    typeof value.changes_requested === 'boolean' &&
    isGitHubUser(value.author) &&
    Array.isArray(value.assignees) &&
    value.assignees.every(isGitHubUser) &&
    Array.isArray(value.requested_reviewers) &&
    value.requested_reviewers.every(isGitHubUser) &&
    (value.linked_jira_key === null || isNonEmptyString(value.linked_jira_key))
  )
}


function isJiraIssue(value: unknown): value is JiraIssue {
  if (!isRecord(value)) {
    return false
  }

  // Jira permits an unassigned issue, represented by null. When an assignee is
  // present, both its stable account ID and display name must be valid strings.
  const assigneeIsValid =
    value.assignee === null ||
    (isRecord(value.assignee) &&
      isNonEmptyString(value.assignee.account_id) &&
      isNonEmptyString(value.assignee.display_name))

  return (
    isNonEmptyString(value.issue_key) &&
    isOneOf(value.status, ['to_do', 'in_progress', 'done']) &&
    isOneOf(value.blocker_state, ['blocked', 'not_blocked']) &&
    assigneeIsValid
  )
}


export function parseScenarioCatalog(value: unknown): FixtureScenario[] {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new ConnectorApiError('The scenario catalog response is malformed.')
  }

  const items = value.items
  const everyItemIsValid = items.every(
    (item): item is FixtureScenario =>
      isRecord(item) &&
      isNonEmptyString(item.id) &&
      isNonEmptyString(item.label) &&
      isConnectorRequest(item.request),
  )

  if (!everyItemIsValid) {
    throw new ConnectorApiError('The scenario catalog response is malformed.')
  }

  return items
}


function isPolicyFinding(value: unknown): value is PolicyFinding {
  return (
    isRecord(value) &&
    isOneOf(value.reason_code, POLICY_REASON_CODES) &&
    isNonEmptyString(value.message) &&
    Array.isArray(value.evidence_reference_ids) &&
    value.evidence_reference_ids.every(isNonEmptyString)
  )
}


function isPendingAction(value: unknown): value is PendingAction {
  return (
    isRecord(value) &&
    isOneOf(value.action_code, PENDING_ACTION_CODES) &&
    isOneOf(value.reason_code, POLICY_REASON_CODES) &&
    isNonEmptyString(value.message)
  )
}


function isEvidenceReference(value: unknown): value is EvidenceReference {
  const evidenceValueIsValid =
    value !== null &&
    isRecord(value) &&
    (typeof value.value === 'string' ||
      typeof value.value === 'boolean' ||
      (typeof value.value === 'number' && Number.isSafeInteger(value.value)) ||
      value.value === null)

  return (
    evidenceValueIsValid &&
    isNonEmptyString(value.reference_id) &&
    isOneOf(value.source, ['github', 'jira']) &&
    isNonEmptyString(value.field)
  )
}


function isMergeReadinessResult(value: unknown): value is MergeReadinessResult {
  return (
    isRecord(value) &&
    isOneOf(value.decision, ['ready', 'blocked', 'unknown']) &&
    isNonEmptyString(value.summary) &&
    isOneOf(value.reason_code, POLICY_REASON_CODES) &&
    Array.isArray(value.blockers) &&
    value.blockers.every(isPolicyFinding) &&
    Array.isArray(value.pending_actions) &&
    value.pending_actions.every(isPendingAction) &&
    Array.isArray(value.missing_information) &&
    value.missing_information.every(isPolicyFinding) &&
    Array.isArray(value.evidence_references) &&
    value.evidence_references.every(isEvidenceReference)
  )
}


export function parseMergeReadiness(
  value: unknown,
): PullRequestMergeReadiness {
  if (
    !isRecord(value) ||
    !isConnectorRequest(value.request) ||
    !(value.github === null || isGitHubPullRequest(value.github)) ||
    !(value.jira === null || isJiraIssue(value.jira)) ||
    !isMergeReadinessResult(value.policy_result)
  ) {
    throw new ConnectorApiError('The merge-readiness response is malformed.')
  }

  // Reconstructing the object after guards makes the proven types explicit to
  // both TypeScript and a reader. No unchecked `as PullRequestInspection` cast
  // crosses this network boundary.
  return {
    request: value.request,
    github: value.github,
    jira: value.jira,
    policy_result: value.policy_result,
  }
}
