import { ConnectorApiError } from './apiError'
import type { CodeFindingCategory, CorrelationIssue, GroundedCodeFinding } from './api'
import { repositoryRelativePath } from './whylinePath'

/** Convert known HTTP outcomes and backend enums into the compact V1 language. */
/** Preserve endpoint-specific backend messages for auth and credential actions. */
export function whylineErrorMessage(error: unknown): string {
  return error instanceof ConnectorApiError ? error.message : 'Something went wrong. Please try again.'
}

/** Scan-only HTTP translation. A 409 on registration has a different meaning. */
export function whylineScanErrorMessage(error: unknown): string {
  const status = error instanceof ConnectorApiError ? error.status : undefined
  if (status === 409) return 'Required source is not connected.'
  if (status === 422) return 'Check the entered values.'
  if (status === 502 || status === 503) return 'A connected provider is temporarily unavailable.'
  return whylineErrorMessage(error)
}

/** Names the affected source without exposing provider response details. */
export function whylineDiscoveryErrorMessage(provider: 'GitHub' | 'Sentry', error: unknown): string {
  const status = error instanceof ConnectorApiError ? error.status : undefined
  if (status === 409) return `Connect ${provider} to choose a ${provider === 'GitHub' ? 'repository' : 'project'}.`
  if (status === 401) return `${provider} credentials need to be reconnected.`
  if (status === 502 || status === 503) return `${provider} is temporarily unavailable. Try again.`
  return whylineErrorMessage(error)
}

export function whylineAnalysisLabel(status: CorrelationIssue['analysis']['status']): string {
  return {
    completed: 'Grounded',
    insufficient_evidence: 'Insufficient evidence',
    no_validated_hypothesis: 'No grounded hypothesis',
    code_finding_unavailable: 'Cause grounded · code location unavailable',
    hypothesis_generation_failed: 'Analysis unavailable',
    analysis_error: 'Analysis unavailable',
  }[status]
}

export function whylineCategoryLabel(category: CodeFindingCategory): string {
  return {
    changed_code_near_failure: 'Changed code near failure',
    error_handling_or_null_path: 'Error handling / invalid state',
    input_validation: 'Input validation',
    state_or_resource_lifecycle: 'State / resource lifecycle',
    configuration_or_deployment: 'Configuration / deployment',
  }[category]
}

export function whylineGroundingLabel(
  strength: CorrelationIssue['presentation']['grounding_strength'],
): string {
  return {
    strong: 'Strong grounding',
    moderate: 'Moderate grounding',
    insufficient: 'Insufficient evidence',
  }[strength]
}

/** The `file · Line N · function()` pieces shared by every location display on the result page. */
export function whylineLocationParts(
  filePath: string | null,
  lineNumber: number | null,
  functionName: string | null,
  repositoryName?: string | null,
): string[] {
  const parts: string[] = []
  if (filePath) parts.push(repositoryRelativePath(filePath, repositoryName))
  if (lineNumber !== null) parts.push(`Line ${lineNumber}`)
  if (functionName) parts.push(`${functionName}()`)
  return parts
}

/**
 * The one-line "what broke, where, what should change" summary shown under
 * the failure title. It only joins backend-authored sentences that already
 * exist on the issue (the top hypothesis statement and the top proposed
 * fix's strategy) -- it never composes new factual claims.
 */
export function whylineFailureSummary(issue: CorrelationIssue): string | null {
  const hypothesis = issue.analysis.hypotheses[0]?.statement.trim() || null
  const strategy = issue.analysis.proposed_fixes[0]?.fix_strategy.trim() || null
  if (hypothesis && strategy) return `${hypothesis} ${strategy}`
  return hypothesis ?? strategy
}

export type WhylineCodeFindingGroup = {
  primary: GroundedCodeFinding
  supportingCount: number
  duplicates: GroundedCodeFinding[]
}

/**
 * Collapse code findings that name the same file, function, line, and
 * category into one presentation group instead of rendering repeated
 * near-identical evidence cards.
 */
export function groupCodeFindings(findings: readonly GroundedCodeFinding[]): WhylineCodeFindingGroup[] {
  const order: string[] = []
  const groups = new Map<string, GroundedCodeFinding[]>()
  for (const finding of findings) {
    const key = [finding.file_path, finding.function_name ?? '', finding.line_number ?? '', finding.category].join('::')
    const existing = groups.get(key)
    if (existing) existing.push(finding)
    else { groups.set(key, [finding]); order.push(key) }
  }
  return order.map((key) => {
    const group = groups.get(key) as GroundedCodeFinding[]
    return { primary: group[0], supportingCount: group.length, duplicates: group.slice(1) }
  })
}
