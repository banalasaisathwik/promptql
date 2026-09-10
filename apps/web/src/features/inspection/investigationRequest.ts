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


// Keep this predicate identical to the backend's
// investigations.models.has_required_grounding_reference. The form converts
// blank strings to null before calling it, just as the API request does.
export function hasRequiredGroundingReference(
  incidentReference: string | null,
  pullRequestNumber: number | null,
  deploymentReference: string | null,
): boolean {
  return !(
    incidentReference === null
    && pullRequestNumber === null
    && deploymentReference === null
  )
}


export function formHasRequiredGroundingReference(
  form: typeof EMPTY_INVESTIGATION_FORM,
): boolean {
  const pullRequestNumber = form.pull_request_number.trim()
    ? Number(form.pull_request_number)
    : null
  const validPullRequestNumber = pullRequestNumber !== null
    && Number.isSafeInteger(pullRequestNumber)
    && pullRequestNumber > 0
    ? pullRequestNumber
    : null

  return hasRequiredGroundingReference(
    form.incident_reference.trim() || null,
    validPullRequestNumber,
    form.deployment_reference.trim() || null,
  )
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
  const incidentReference = form.incident_reference.trim() || null
  const deploymentReference = form.deployment_reference.trim() || null
  if (!hasRequiredGroundingReference(
    incidentReference,
    parsedPullRequestNumber,
    deploymentReference,
  )) {
    return 'At least one incident, deployment, or pull request is required.'
  }
  return {
    repository_owner: form.repository_owner.trim(),
    repository_name: form.repository_name.trim(),
    question: form.question.trim(),
    incident_reference: incidentReference,
    deployment_reference: deploymentReference,
    pull_request_number: parsedPullRequestNumber,
    service: form.service.trim() || null,
    environment: form.environment.trim() || null,
  }
}
