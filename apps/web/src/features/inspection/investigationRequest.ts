import type { InvestigationRequest } from './types'


export const EMPTY_INVESTIGATION_FORM = {
  question: '',
  repository_owner: '',
  repository_name: '',
  incident_reference: '',
  deployment_reference: '',
  pull_request_number: '',
  service: '',
  environment: '',
}


// This preset is an editable browser-side draft, not a new runtime scenario.
// Its values match the existing fake connector keys so demo users do not start
// an investigation that fails solely because a fixture is unavailable.
export const CHECKOUT_500_PRESET = {
  question: 'Why did checkout start returning 500s after the latest deployment?',
  repository_owner: 'octo-org',
  repository_name: 'analytics',
  incident_reference: 'incident:checkout-500',
  deployment_reference: 'deployment:1042',
  pull_request_number: '42',
  service: 'checkout-api',
  environment: 'production',
}


export function buildInvestigationRequest(
  form: typeof EMPTY_INVESTIGATION_FORM,
): InvestigationRequest | string {
  // The question is validated separately because it is the user-owned goal;
  // repository details validate the distinct GitHub evidence boundary.
  if (!form.question.trim()) {
    return 'What do you want to investigate? is required.'
  }
  if (!form.repository_owner.trim() || !form.repository_name.trim()) {
    return 'Repository owner and repository name are required.'
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
    question: form.question.trim(),
    incident_reference: form.incident_reference.trim() || null,
    deployment_reference: form.deployment_reference.trim() || null,
    pull_request_number: parsedPullRequestNumber,
    service: form.service.trim() || null,
    environment: form.environment.trim() || null,
  }
}
