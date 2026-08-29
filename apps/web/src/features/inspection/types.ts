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

export interface MergeReadinessExplanation {
  decision: MergeReadinessDecision
  summary: string
  reasons: string[]
  recommended_actions: string[]
}

export type ExplanationErrorCode =
  | 'provider_failure'
  | 'invalid_output'
  | 'validation_failed'

export interface ExplanationApiError {
  code: ExplanationErrorCode
  message: string
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

export type ConnectorSource = 'fake' | 'live'
export type ExplanationSource = 'fake' | 'gemini' | 'groq' | 'openai'

export interface RunSources {
  github: ConnectorSource | null
  jira: ConnectorSource | null
  explanation: ExplanationSource | null
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

interface MergeReadinessRunBase {
  run_id: string
  workflow_name: string
  workflow_version: string
  sources: RunSources | null
  started_at: string | null
  completed_at: string | null
  steps: RuntimeStep[]
  request: ConnectorRequest
  github: GitHubPullRequest | null
  jira: JiraIssue | null
}

export interface CompletedMergeReadinessRun extends MergeReadinessRunBase {
  status: 'completed'
  error: null
  result: MergeReadinessResult
  explanation: MergeReadinessExplanation | null
  explanation_error: ExplanationApiError | null
}

export interface FailedMergeReadinessRun extends MergeReadinessRunBase {
  status: 'failed'
  error: RuntimeErrorInfo
  result: null
  explanation: null
  explanation_error: null
}

export interface PendingMergeReadinessRun extends MergeReadinessRunBase {
  status: 'pending'
  error: null
  result: null
  explanation: null
  explanation_error: null
}

export interface RunningMergeReadinessRun extends MergeReadinessRunBase {
  status: 'running'
  error: null
  result: null
  explanation: null
  explanation_error: null
}

export interface CancelledMergeReadinessRun extends MergeReadinessRunBase {
  status: 'cancelled'
  error: RuntimeErrorInfo | null
  result: null
  explanation: null
  explanation_error: null
}

export type TerminalMergeReadinessRun =
  | CompletedMergeReadinessRun
  | FailedMergeReadinessRun
  | CancelledMergeReadinessRun

export type PullRequestMergeReadiness =
  | TerminalMergeReadinessRun
  | PendingMergeReadinessRun
  | RunningMergeReadinessRun

export interface LiveRunStart {
  run_id: string
  status: 'pending'
}

// ADR-033: accepting a follow-up reopens an already-completed case straight
// to running (there is no separate pending-follow-up state), unlike starting
// a brand-new investigation above.
export interface FollowUpRunStart {
  run_id: string
  status: 'running'
}

export interface InvestigationRequest {
  repository_owner: string
  repository_name: string
  question: string
  incident_reference?: string | null
  deployment_reference?: string | null
  pull_request_number?: number | null
  jira_issue_key?: string | null
  service?: string | null
  environment?: string | null
}

// The extraction endpoint only proposes grounding fields; it never creates a
// run. known_* fields let a caller that already filled part of the structured
// form pass those along so extraction does not re-derive or contradict them.
export interface GroundingExtractionInput {
  description: string
  known_repository_owner?: string | null
  known_repository_name?: string | null
  known_incident_reference?: string | null
  known_deployment_reference?: string | null
  known_pull_request_number?: number | null
}

export interface GroundingExtractionOutput {
  repository_owner: string | null
  repository_name: string | null
  incident_reference: string | null
  deployment_reference: string | null
  pull_request_number: number | null
}

export type GroundingExtractionStatus = 'complete' | 'needs_clarification'

export type MissingGroundingField =
  | 'incident_reference'
  | 'deployment_reference'
  | 'pull_request_number'

export interface GroundingExtractionResponse {
  status: GroundingExtractionStatus
  extracted: GroundingExtractionOutput
  missing: MissingGroundingField[]
  question: string | null
}

export interface InvestigationEvidence {
  evidence_id: string
  source: string
  kind: string
  provenance: {
    source_reference: string
    observed_at: string | null
    retrieved_at: string
  }
  content: Record<string, unknown>
}

export interface InvestigationFact {
  fact_id: string
  fact_type: string
  evidence_reference_ids: string[]
  [key: string]: unknown
}

export interface InvestigationMissingInformation {
  missing_information_id: string
  kind: string
  detail: string | null
  related_fact_ids: string[]
  related_hypothesis_ids: string[]
}

export type InvestigationStepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'blocked'

export interface InvestigationStepSnapshot {
  step_id: string
  tool_id: string
  status: InvestigationStepStatus
  attempts: number
  failure_code: string | null
  failure_message: string | null
  block_reason: string | null
}

export interface InvestigationPlanningRound {
  round_number: number
  plan_id: string
  plan_validation_status: string
  steps: InvestigationStepSnapshot[]
  evidence_delta_ids: string[]
  fact_delta_ids: string[]
  completed: boolean
}

export interface ValidatedHypothesis {
  hypothesis_id: string
  kind: string
  subject: string
  supporting_fact_ids: string[]
}

export interface GroundedHypothesis extends ValidatedHypothesis {
  statement: string
  // The deterministic backend only attaches this when its relationship graph
  // can prove a clean chain between the hypothesis's cited entities.
  connected_fact_chain?: string[] | null
}

export interface ValidatedCodeFinding {
  // Exact coordinates exist only after backend Evidence resolution. These
  // fields describe API truth; they are not candidate model output.
  finding_id: string
  hypothesis_id: string
  file_path: string
  line_number: number | null
  function_name: string | null
  hunk_evidence_id: string | null
  category: string
  supporting_fact_ids: string[]
  supporting_evidence_ids: string[]
}

export interface GroundedCodeFinding extends ValidatedCodeFinding {
  statement: string
}

export interface DeveloperRecommendation {
  recommendation_id: string
  code: string
  message: string
  finding_id: string
  supporting_fact_ids: string[]
  supporting_evidence_ids: string[]
}

export interface GenerationMetadata {
  task: string
  provider: string
  model: string
  requested_model: string | null
  resolved_model: string | null
  prompt_id: string
  prompt_version: string
  token_usage: {
    input_tokens: number
    output_tokens: number
    total_tokens: number | null
  } | null
}

export interface GroundedInvestigationResult {
  termination_reason: string
  summary: string
  supported_hypotheses: GroundedHypothesis[]
  code_findings: GroundedCodeFinding[]
  recommendations: DeveloperRecommendation[]
  key_fact_ids: string[]
  missing_information: InvestigationMissingInformation[]
}

export type InvestigationToolOutcome = 'observed' | 'empty' | 'failed'

export interface InvestigationActionSummary {
  tool_id: string
  outcome: InvestigationToolOutcome
  produced_new_evidence: boolean
  produced_new_facts: boolean
}

// Semantic investigation knowledge: what the investigation has learned so far.
export interface WorkingMemoryState {
  // Bare evidence IDs referenced by planning rounds/facts/findings, for a
  // lightweight trace/flow view. Full content lives in `evidence_content`.
  evidence: string[]
  evidence_content: InvestigationEvidence[]
  facts: InvestigationFact[]
  missing_information: InvestigationMissingInformation[]
  validated_hypotheses: ValidatedHypothesis[]
  validated_code_findings: ValidatedCodeFinding[]
  developer_recommendations: DeveloperRecommendation[]
  action_history: InvestigationActionSummary[]
}

// Pure execution bookkeeping: how the run has progressed.
export interface ExecutionState {
  rounds: InvestigationPlanningRound[]
  hypothesis_generation_metadata: GenerationMetadata | null
  rejected_hypothesis_count: number
  code_diagnosis_metadata: GenerationMetadata | null
  rejected_code_finding_count: number
  max_tool_calls: number
  used_tool_calls: number
  remaining_tool_calls: number
  termination_reason: string | null
}

export interface InvestigationRuntimeState {
  working_memory: WorkingMemoryState
  execution_state: ExecutionState
}

export interface InvestigationRuntimeError {
  code: string
  message: string
}

interface InvestigationRunBase {
  run_id: string
  workflow_name: 'investigation'
  workflow_version: string
  status: RuntimeStatus
  started_at: string | null
  completed_at: string | null
  steps: []
  request: InvestigationRequest
}

export interface InvestigationRun extends InvestigationRunBase {
  error: InvestigationRuntimeError | null
  state: InvestigationRuntimeState | null
  // Ordered, append-only: the original investigation's result is always
  // index 0; each follow-up (ADR-033) appends one more entry after it. A
  // completed investigation has at least one entry; a pending investigation
  // has none.
  results: GroundedInvestigationResult[]
}

export type RuntimeRun = PullRequestMergeReadiness | InvestigationRun

// One structured event from GET /v1/runs/{run_id}/events. The backend closes
// which fields any event may carry behind an allowlist (see
// StructuredEventLogger.ALLOWED_EVENT_FIELDS); this type mirrors that
// envelope/payload split rather than hardcoding every possible field name, so
// the frontend does not need a matching edit whenever the backend allowlist
// grows.
export interface LiveRunEvent {
  event: string
  level: string
  timestamp: string
  run_id?: string
  trace_id?: string
  span_id?: string
  fields: Record<string, string | number | boolean>
}
