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
  ExplanationApiError,
  FixtureScenario,
  GitHubPullRequest,
  GitHubUser,
  JiraIssue,
  MergeReadinessResult,
  MergeReadinessExplanation,
  PendingAction,
  PolicyFinding,
  PullRequestMergeReadiness,
  InvestigationRun,
  InvestigationEvidence,
  InvestigationFact,
  InvestigationMissingInformation,
  InvestigationPlanningRound,
  InvestigationRuntimeState,
  InvestigationStepSnapshot,
  GroundedInvestigationResult,
  ValidatedHypothesis,
  RuntimeRun,
  RequiredCheck,
  RuntimeErrorInfo,
  RuntimeStep,
  RunSources,
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

const RUNTIME_ERROR_CODES = [
  'connector_execution_failed',
  'policy_execution_failed',
  'fixture_not_found',
] as const

const RUNTIME_STATUSES = [
  'pending',
  'running',
  'completed',
  'failed',
  'cancelled',
] as const

const WORKFLOW_STEP_NAMES = [
  'fetch_github_facts',
  'fetch_jira_facts',
  'evaluate_merge_readiness',
] as const

const EXPLANATION_ERROR_CODES = [
  'provider_failure',
  'invalid_output',
  'validation_failed',
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
    Number.isSafeInteger(value.pr_number) &&
    Number(value.pr_number) > 0 &&
    isNonEmptyString(value.title) &&
    isNonEmptyString(value.url) &&
    isNonEmptyString(value.head_branch) &&
    isNonEmptyString(value.base_branch) &&
    isOneOf(value.state, ['open', 'closed', 'merged']) &&
    typeof value.is_draft === 'boolean' &&
    isOneOf(value.mergeability, ['mergeable', 'conflicting', 'unknown']) &&
    Array.isArray(value.required_checks) &&
    value.required_checks.every(isRequiredCheck) &&
    typeof value.required_checks_known === 'boolean' &&
    Array.isArray(value.approvals) &&
    value.approvals.every(isGitHubUser) &&
    (value.required_approval_count === null ||
      (Number.isSafeInteger(value.required_approval_count) &&
        Number(value.required_approval_count) >= 0)) &&
    typeof value.reviews_known === 'boolean' &&
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
    isOneOf(value.blocker_state, ['blocked', 'not_blocked', 'unknown']) &&
    assigneeIsValid &&
    (value.status_id === null || isNonEmptyString(value.status_id)) &&
    (value.status_name === null || isNonEmptyString(value.status_name)) &&
    (value.is_resolved === null || typeof value.is_resolved === 'boolean')
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


function isMergeReadinessExplanation(
  value: unknown,
): value is MergeReadinessExplanation {
  return (
    isRecord(value) &&
    isOneOf(value.decision, ['ready', 'blocked', 'unknown']) &&
    isNonEmptyString(value.summary) &&
    Array.isArray(value.reasons) &&
    value.reasons.every(isNonEmptyString) &&
    Array.isArray(value.recommended_actions) &&
    value.recommended_actions.every(isNonEmptyString)
  )
}


function isExplanationApiError(value: unknown): value is ExplanationApiError {
  return (
    isRecord(value) &&
    isOneOf(value.code, EXPLANATION_ERROR_CODES) &&
    isNonEmptyString(value.message)
  )
}


function isTimestamp(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value))
}


function isRuntimeError(value: unknown): value is RuntimeErrorInfo {
  return (
    isRecord(value) &&
    isOneOf(value.code, RUNTIME_ERROR_CODES) &&
    isNonEmptyString(value.message)
  )
}


function isRuntimeStep(value: unknown): value is RuntimeStep {
  return (
    isRecord(value) &&
    isNonEmptyString(value.step_id) &&
    isOneOf(value.name, WORKFLOW_STEP_NAMES) &&
    isOneOf(value.status, RUNTIME_STATUSES) &&
    (value.started_at === null || isTimestamp(value.started_at)) &&
    (value.completed_at === null || isTimestamp(value.completed_at)) &&
    (value.duration_ms === null ||
      (Number.isSafeInteger(value.duration_ms) &&
        Number(value.duration_ms) >= 0)) &&
    Number.isSafeInteger(value.attempt) &&
    Number(value.attempt) > 0 &&
    (value.error === null || isRuntimeError(value.error))
  )
}


function isRunSources(value: unknown): value is RunSources {
  return (
    isRecord(value) &&
    (value.github === null || isOneOf(value.github, ['fake', 'live'])) &&
    (value.jira === null || isOneOf(value.jira, ['fake', 'live'])) &&
    (value.explanation === null ||
      isOneOf(value.explanation, ['fake', 'gemini', 'groq', 'openai']))
  )
}


function hasCompletedRunState(
  value: Record<string, unknown>,
): value is Record<string, unknown> & {
  status: 'completed'
  error: null
  result: MergeReadinessResult
} {
  return (
    value.status === 'completed' &&
    value.error === null &&
    isMergeReadinessResult(value.result)
  )
}


function hasFailedRunState(
  value: Record<string, unknown>,
): value is Record<string, unknown> & {
  status: 'failed'
  error: RuntimeErrorInfo
  result: null
  explanation: null
  explanation_error: null
} {
  return (
    value.status === 'failed' &&
    isRuntimeError(value.error) &&
    value.result === null &&
    value.explanation === null &&
    value.explanation_error === null
  )
}


function hasActiveRunState(
  value: Record<string, unknown>,
): value is Record<string, unknown> & {
  status: 'pending' | 'running'
  error: null
  result: null
  explanation: null
  explanation_error: null
} {
  return (
    isOneOf(value.status, ['pending', 'running']) &&
    value.error === null &&
    value.result === null &&
    value.explanation === null &&
    value.explanation_error === null
  )
}


function hasCancelledRunState(
  value: Record<string, unknown>,
): value is Record<string, unknown> & {
  status: 'cancelled'
  error: RuntimeErrorInfo | null
  result: null
  explanation: null
  explanation_error: null
} {
  return (
    value.status === 'cancelled' &&
    (value.error === null || isRuntimeError(value.error)) &&
    value.result === null &&
    value.explanation === null &&
    value.explanation_error === null
  )
}


export function parseMergeReadiness(
  value: unknown,
): PullRequestMergeReadiness {
  const explanationIsValid =
    isRecord(value) &&
    (value.explanation === null ||
      isMergeReadinessExplanation(value.explanation))
  const explanationErrorIsValid =
    isRecord(value) &&
    (value.explanation_error === null ||
      isExplanationApiError(value.explanation_error))
  const completedExplanationOutcomeIsValid =
    isRecord(value) &&
    (value.status !== 'completed' ||
      (value.explanation !== null && value.explanation_error === null) ||
      (value.explanation === null && value.explanation_error !== null))
  const sourcesAreValid =
    isRecord(value) &&
    (value.sources === undefined ||
      value.sources === null ||
      isRunSources(value.sources))
  const completedRunIsValid = isRecord(value) && hasCompletedRunState(value)
  const failedRunIsValid = isRecord(value) && hasFailedRunState(value)
  const activeRunIsValid = isRecord(value) && hasActiveRunState(value)
  const cancelledRunIsValid = isRecord(value) && hasCancelledRunState(value)

  if (
    !isRecord(value) ||
    !isNonEmptyString(value.run_id) ||
    !isNonEmptyString(value.workflow_name) ||
    !isNonEmptyString(value.workflow_version) ||
    !(completedRunIsValid || failedRunIsValid || activeRunIsValid || cancelledRunIsValid) ||
    !(value.started_at === null || isTimestamp(value.started_at)) ||
    !(value.completed_at === null || isTimestamp(value.completed_at)) ||
    !Array.isArray(value.steps) ||
    !value.steps.every(isRuntimeStep) ||
    !isConnectorRequest(value.request) ||
    !(value.github === null || isGitHubPullRequest(value.github)) ||
    !(value.jira === null || isJiraIssue(value.jira)) ||
    !explanationIsValid ||
    !explanationErrorIsValid ||
    !completedExplanationOutcomeIsValid ||
    !sourcesAreValid ||
    (isMergeReadinessExplanation(value.explanation) &&
      isMergeReadinessResult(value.result) &&
      value.explanation.decision !== value.result.decision)
  ) {
    throw new ConnectorApiError('The merge-readiness response is malformed.')
  }

  const commonRun = {
    run_id: value.run_id,
    workflow_name: value.workflow_name,
    workflow_version: value.workflow_version,
    sources: isRunSources(value.sources) ? value.sources : null,
    started_at: value.started_at as string | null,
    completed_at: value.completed_at as string | null,
    steps: value.steps,
    request: value.request,
    github: value.github,
    jira: value.jira,
  }

  if (hasFailedRunState(value)) {
    return {
      ...commonRun,
      status: value.status,
      error: value.error,
      result: value.result,
      explanation: value.explanation,
      explanation_error: value.explanation_error,
    }
  }

  if (hasActiveRunState(value)) {
    return {
      ...commonRun,
      status: value.status,
      error: null,
      result: null,
      explanation: null,
      explanation_error: null,
    }
  }

  if (hasCancelledRunState(value)) {
    return {
      ...commonRun,
      status: value.status,
      error: value.error,
      result: null,
      explanation: null,
      explanation_error: null,
    }
  }

  // The earlier guard proved that a non-failed body is a completed body.
  if (!hasCompletedRunState(value)) {
    throw new ConnectorApiError('The merge-readiness response is malformed.')
  }
  return {
    ...commonRun,
    status: value.status,
    error: value.error,
    result: value.result,
    explanation: isMergeReadinessExplanation(value.explanation)
      ? value.explanation
      : null,
    explanation_error: isExplanationApiError(value.explanation_error)
      ? value.explanation_error
      : null,
  }
}


export function parseLiveRunStart(value: unknown): {
  run_id: string
  status: 'pending'
} {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.run_id) ||
    value.status !== 'pending'
  ) {
    throw new ConnectorApiError('The live-run start response is malformed.')
  }
  return { run_id: value.run_id, status: value.status }
}


function isInvestigationRequest(value: unknown): boolean {
  return (
    isRecord(value) &&
    isNonEmptyString(value.repository_owner) &&
    isNonEmptyString(value.repository_name) &&
    isNonEmptyString(value.question)
  )
}


function isInvestigationEvidence(value: unknown): value is InvestigationEvidence {
  return (
    isRecord(value) &&
    isNonEmptyString(value.evidence_id) &&
    isNonEmptyString(value.source) &&
    isNonEmptyString(value.kind) &&
    isRecord(value.provenance) &&
    isNonEmptyString(value.provenance.source_reference) &&
    isTimestamp(value.provenance.retrieved_at) &&
    isRecord(value.content)
  )
}


function isInvestigationFact(value: unknown): value is InvestigationFact {
  return (
    isRecord(value) &&
    isNonEmptyString(value.fact_id) &&
    isNonEmptyString(value.fact_type) &&
    Array.isArray(value.evidence_reference_ids) &&
    value.evidence_reference_ids.every(isNonEmptyString)
  )
}


function isMissingInformation(value: unknown): value is InvestigationMissingInformation {
  return (
    isRecord(value) &&
    isNonEmptyString(value.missing_information_id) &&
    isNonEmptyString(value.kind) &&
    (value.detail === null || isNonEmptyString(value.detail)) &&
    Array.isArray(value.related_fact_ids) &&
    value.related_fact_ids.every(isNonEmptyString) &&
    Array.isArray(value.related_hypothesis_ids) &&
    value.related_hypothesis_ids.every(isNonEmptyString)
  )
}


function isInvestigationStep(value: unknown): value is InvestigationStepSnapshot {
  return (
    isRecord(value) &&
    isNonEmptyString(value.step_id) &&
    isNonEmptyString(value.tool_id) &&
    isOneOf(value.status, ['pending', 'running', 'succeeded', 'failed', 'blocked']) &&
    Number.isSafeInteger(value.attempts) &&
    Number(value.attempts) >= 0 &&
    (value.failure_code === null || isNonEmptyString(value.failure_code)) &&
    (value.failure_message === null || isNonEmptyString(value.failure_message)) &&
    (value.block_reason === null || isNonEmptyString(value.block_reason))
  )
}


function isInvestigationRound(value: unknown): value is InvestigationPlanningRound {
  return (
    isRecord(value) &&
    Number.isSafeInteger(value.round_number) &&
    Number(value.round_number) > 0 &&
    isNonEmptyString(value.plan_id) &&
    isNonEmptyString(value.plan_validation_status) &&
    Array.isArray(value.steps) &&
    value.steps.every(isInvestigationStep) &&
    Array.isArray(value.evidence_delta_ids) &&
    value.evidence_delta_ids.every(isNonEmptyString) &&
    Array.isArray(value.fact_delta_ids) &&
    value.fact_delta_ids.every(isNonEmptyString) &&
    typeof value.completed === 'boolean'
  )
}


function isValidatedHypothesis(value: unknown): value is ValidatedHypothesis {
  return (
    isRecord(value) &&
    isNonEmptyString(value.hypothesis_id) &&
    isNonEmptyString(value.kind) &&
    isNonEmptyString(value.subject) &&
    Array.isArray(value.supporting_fact_ids) &&
    value.supporting_fact_ids.every(isNonEmptyString)
  )
}


function isGroundedHypothesis(
  value: unknown,
): value is ValidatedHypothesis & { statement: string } {
  return isRecord(value) && isValidatedHypothesis(value) && isNonEmptyString(value.statement)
}


function isGroundedResult(value: unknown): value is GroundedInvestigationResult {
  return (
    isRecord(value) &&
    isNonEmptyString(value.termination_reason) &&
    isNonEmptyString(value.summary) &&
    Array.isArray(value.supported_hypotheses) &&
    value.supported_hypotheses.every(
      isGroundedHypothesis,
    ) &&
    Array.isArray(value.key_fact_ids) &&
    value.key_fact_ids.every(isNonEmptyString) &&
    Array.isArray(value.missing_information) &&
    value.missing_information.every(isMissingInformation)
  )
}


function isInvestigationState(value: unknown): value is InvestigationRuntimeState {
  return (
    isRecord(value) &&
    Array.isArray(value.rounds) &&
    value.rounds.every(isInvestigationRound) &&
    Array.isArray(value.evidence) &&
    value.evidence.every(isInvestigationEvidence) &&
    Array.isArray(value.facts) &&
    value.facts.every(isInvestigationFact) &&
    Array.isArray(value.missing_information) &&
    value.missing_information.every(isMissingInformation) &&
    Array.isArray(value.validated_hypotheses) &&
    value.validated_hypotheses.every(isValidatedHypothesis) &&
    Number.isSafeInteger(value.rejected_hypothesis_count) &&
    Number(value.rejected_hypothesis_count) >= 0 &&
    Number.isSafeInteger(value.max_tool_calls) &&
    Number(value.max_tool_calls) >= 0 &&
    Number.isSafeInteger(value.used_tool_calls) &&
    Number(value.used_tool_calls) >= 0 &&
    Number.isSafeInteger(value.remaining_tool_calls) &&
    Number(value.remaining_tool_calls) >= 0 &&
    (value.termination_reason === null || isNonEmptyString(value.termination_reason))
  )
}


export function parseInvestigationRun(value: unknown): InvestigationRun {
  if (
    !isRecord(value) ||
    value.workflow_name !== 'investigation' ||
    !isNonEmptyString(value.run_id) ||
    !isNonEmptyString(value.workflow_version) ||
    !isOneOf(value.status, RUNTIME_STATUSES) ||
    !(value.started_at === null || isTimestamp(value.started_at)) ||
    !(value.completed_at === null || isTimestamp(value.completed_at)) ||
    !Array.isArray(value.steps) ||
    value.steps.length !== 0 ||
    !isInvestigationRequest(value.request) ||
    !(value.error === null || isRecord(value.error)) ||
    !(value.state === null || isInvestigationState(value.state)) ||
    !(value.result === null || isGroundedResult(value.result))
  ) {
    throw new ConnectorApiError('The investigation response is malformed.')
  }

  if (value.status === 'completed' &&
      (value.error !== null || !isInvestigationState(value.state) || !isGroundedResult(value.result))) {
    throw new ConnectorApiError('The investigation response is malformed.')
  }
  if ((value.status === 'pending' || value.status === 'running') &&
      (value.error !== null || value.result !== null)) {
    throw new ConnectorApiError('The investigation response is malformed.')
  }
  if (value.status === 'failed' &&
      (!isRecord(value.error) || !isNonEmptyString(value.error.code) || !isNonEmptyString(value.error.message) || value.result !== null)) {
    throw new ConnectorApiError('The investigation response is malformed.')
  }

  return {
    run_id: value.run_id,
    workflow_name: 'investigation',
    workflow_version: value.workflow_version,
    status: value.status,
    started_at: value.started_at as string | null,
    completed_at: value.completed_at as string | null,
    steps: [],
    request: value.request as InvestigationRun['request'],
    error: value.error as InvestigationRun['error'],
    state: value.state as InvestigationRun['state'],
    result: value.result as InvestigationRun['result'],
  }
}


export function parseRuntimeRun(value: unknown): RuntimeRun {
  if (isRecord(value) && value.workflow_name === 'investigation') {
    return parseInvestigationRun(value)
  }
  return parseMergeReadiness(value)
}
