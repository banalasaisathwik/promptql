import { ConnectorApiError } from './apiError'
import type { CodeFindingCategory, CorrelationIssue } from './api'

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
