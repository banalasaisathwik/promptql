import type { InvestigationRequest } from './types'


export const EMPTY_INVESTIGATION_FORM = {
  repository_owner: '',
  repository_name: '',
  incident_summary: '',
  incident_reference: '',
  deployment_reference: '',
  pull_request_number: '',
  service: '',
  environment: '',
}


export function buildInvestigationRequest(
  form: typeof EMPTY_INVESTIGATION_FORM,
): InvestigationRequest | string {
  if (!form.repository_owner.trim() || !form.repository_name.trim() || !form.incident_summary.trim()) {
    return 'Repository owner, repository name, and incident summary are required.'
  }
  const parsedPullRequestNumber = form.pull_request_number.trim()
    ? Number(form.pull_request_number)
    : null
  if (parsedPullRequestNumber !== null &&
      (!Number.isSafeInteger(parsedPullRequestNumber) || parsedPullRequestNumber <= 0)) {
    return 'Pull request number must be a positive whole number.'
  }
  return {
    repository_owner: form.repository_owner.trim(),
    repository_name: form.repository_name.trim(),
    incident_summary: form.incident_summary.trim(),
    incident_reference: form.incident_reference.trim() || null,
    deployment_reference: form.deployment_reference.trim() || null,
    pull_request_number: parsedPullRequestNumber,
    service: form.service.trim() || null,
    environment: form.environment.trim() || null,
  }
}
