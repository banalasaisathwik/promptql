/**
 * HTTP transport for connector inspection.
 *
 * This module knows URLs, HTTP methods, JSON encoding, and network errors. It
 * delegates response shape validation to responseValidation.ts and contains no
 * React state or rendering code.
 */

import { ConnectorApiError } from './apiError'
import {
  parseFollowUpRunStart,
  parseGroundingExtractionResponse,
  parseLiveRunStart,
  parseRuntimeRun,
} from './responseValidation'
import type {
  FollowUpRunStart,
  GroundingExtractionInput,
  GroundingExtractionResponse,
  InvestigationRequest,
  LiveRunStart,
  RuntimeRun,
} from './types'


async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    throw new ConnectorApiError(
      'The backend returned a response that was not valid JSON.',
      response.status,
    )
  }
}


async function requestJson(
  url: string,
  init?: RequestInit,
): Promise<unknown> {
  let response: Response

  try {
    response = await fetch(url, { ...init, credentials: 'include' })
  } catch {
    // Browser fetch throws for network failures, not for HTTP 404/500 statuses.
    throw new ConnectorApiError(
      'Could not reach the API. Confirm that the backend server is running.',
    )
  }

  const body = await readJson(response)

  if (!response.ok) {
    throw new ConnectorApiError(apiErrorMessage(body, response.status), response.status)
  }

  return body
}


async function requestMergeReadiness(
  url: string,
  init: RequestInit,
): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(url, { ...init, credentials: 'include' })
  } catch {
    throw new ConnectorApiError(
      'Could not reach the API. Confirm that the backend server is running.',
    )
  }

  const body = await readJson(response)
  // HTTP 500 is an expected transport status for the backend's typed failed-run
  // contract. Parsing it lets the UI show the run ID and completed steps.
  if (response.ok || response.status === 500) {
    return body
  }

  throw new ConnectorApiError(apiErrorMessage(body, response.status), response.status)
}


export async function startInvestigationRun(
  request: InvestigationRequest,
): Promise<LiveRunStart> {
  const body = await requestJson('/v1/investigations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  return parseLiveRunStart(body)
}


export async function extractGrounding(
  input: GroundingExtractionInput,
): Promise<GroundingExtractionResponse> {
  // This call only proposes grounding fields for review; it never starts a run.
  // Starting one still requires the caller to submit through
  // startInvestigationRun, unchanged, above.
  const body = await requestJson('/v1/investigations/extract-grounding', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    // POST responses are not normally cacheable, but this review step must
    // always reflect the description submitted immediately above it.
    cache: 'no-store',
  })
  return parseGroundingExtractionResponse(body)
}


export async function startInvestigationFollowUp(
  runId: string,
  question: string,
): Promise<FollowUpRunStart> {
  // ADR-033: reopens an already-completed case; the backend rejects a
  // not-yet-completed run (409) or an unknown run_id (404) with a message
  // already meant for direct display, so this call adds no extra mapping.
  const body = await requestJson(
    `/v1/investigations/${encodeURIComponent(runId)}/follow-up`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    },
  )
  return parseFollowUpRunStart(body)
}


export async function fetchRuntimeRun(
  runId: string,
  signal?: AbortSignal,
): Promise<RuntimeRun> {
  const body = await requestMergeReadiness(`/v1/runs/${encodeURIComponent(runId)}`, {
    signal,
  })
  return parseRuntimeRun(body)
}


function apiErrorMessage(body: unknown, status: number): string {
  if (isRecord(body) && typeof body.message === 'string') {
    return body.message
  }
  if (isRecord(body) && isRecord(body.error) && typeof body.error.message === 'string') {
    return body.error.message
  }
  if (isRecord(body) && Array.isArray(body.detail)) {
    const detail = body.detail.find(
      (item): item is Record<string, unknown> => isRecord(item) && typeof item.msg === 'string',
    )
    if (detail) return detail.msg as string
  }
  return `The API request failed with status ${status}.`
}


export type CredentialProvider = 'github' | 'jira' | 'sentry'

export type CredentialSource = 'real' | 'demo'

export type CredentialConnectionStatus = {
  connected: boolean
  source: CredentialSource
}

export type CredentialConnections = Record<CredentialProvider, CredentialConnectionStatus>

export type AuthenticatedUser = {
  id: string
  email: string
  createdAt: string
}

export type DemoAccount = {
  email: string
  password: string
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}


function parseAuthenticatedUser(value: unknown): AuthenticatedUser {
  if (
    !isRecord(value) ||
    typeof value.id !== 'string' ||
    typeof value.email !== 'string' ||
    typeof value.created_at !== 'string'
  ) {
    throw new ConnectorApiError('The API response is malformed.')
  }
  return { id: value.id, email: value.email, createdAt: value.created_at }
}


function parseCredentialConnections(value: unknown): CredentialConnections {
  if (!isRecord(value) || !Array.isArray(value.providers)) {
    throw new ConnectorApiError('The API response is malformed.')
  }

  const notConnected: CredentialConnectionStatus = { connected: false, source: 'real' }
  const connections: CredentialConnections = {
    github: notConnected,
    jira: notConnected,
    sentry: notConnected,
  }
  for (const item of value.providers) {
    if (
      !isRecord(item) ||
      !['github', 'jira', 'sentry'].includes(String(item.provider)) ||
      typeof item.connected !== 'boolean' ||
      !['real', 'demo'].includes(String(item.source))
    ) {
      throw new ConnectorApiError('The API response is malformed.')
    }
    connections[item.provider as CredentialProvider] = {
      connected: item.connected,
      source: item.source as CredentialSource,
    }
  }
  return connections
}


async function requestNoContent(url: string, init: RequestInit): Promise<void> {
  let response: Response
  try {
    response = await fetch(url, { ...init, credentials: 'include' })
  } catch {
    throw new ConnectorApiError(
      'Could not reach the API. Confirm that the backend server is running.',
    )
  }

  if (!response.ok) {
    const body = await readJson(response)
    throw new ConnectorApiError(apiErrorMessage(body, response.status), response.status)
  }
}


export async function registerWorkspace(
  email: string,
  password: string,
): Promise<AuthenticatedUser> {
  return parseAuthenticatedUser(await requestJson('/v1/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }))
}


export async function loginWorkspace(
  email: string,
  password: string,
): Promise<AuthenticatedUser> {
  return parseAuthenticatedUser(await requestJson('/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }))
}


export async function logoutWorkspace(): Promise<void> {
  await requestNoContent('/v1/auth/logout', { method: 'POST' })
}

/** Resolve the signed HttpOnly browser session; no frontend token is stored. */
export async function fetchCurrentUser(): Promise<AuthenticatedUser> {
  return parseAuthenticatedUser(await requestJson('/v1/auth/me'))
}


export async function fetchCredentialConnections(): Promise<CredentialConnections> {
  return parseCredentialConnections(await requestJson('/v1/credentials'))
}


function parseDemoAccount(value: unknown): DemoAccount {
  if (
    !isRecord(value) ||
    typeof value.email !== 'string' ||
    typeof value.password !== 'string'
  ) {
    throw new ConnectorApiError('The API response is malformed.')
  }
  return { email: value.email, password: value.password }
}


export async function fetchDemoAccount(): Promise<DemoAccount> {
  // Intentionally unauthenticated and non-secret (ADR-035): the demo
  // account's password is meant to be visible on the public landing page.
  return parseDemoAccount(await requestJson('/v1/demo-account'))
}


export async function connectCredential(
  provider: CredentialProvider,
  token: string,
): Promise<void> {
  await requestJson('/v1/credentials', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, token }),
  })
}


export async function disconnectCredential(provider: CredentialProvider): Promise<void> {
  await requestNoContent(`/v1/credentials/${provider}`, { method: 'DELETE' })
}

export type CorrelationScanRequest = {
  repository_owner: string
  repository_name: string
  sentry_project_slug: string
}

export type GitHubRepository = {
  owner: string
  name: string
  full_name: string
  private: boolean
  default_branch: string | null
}

export type GitHubContext = { login: string, repositories: GitHubRepository[] }
export type SentryProject = {
  organization_slug: string
  project_slug: string
  name: string
}

export async function fetchGitHubContext(): Promise<GitHubContext> {
  return await requestJson('/v1/github/context') as GitHubContext
}

export async function fetchSentryProjects(): Promise<SentryProject[]> {
  return await requestJson('/v1/sentry/projects') as SentryProject[]
}

export type FactSummary = { label: string, detail: string | null }
export type GroundedHypothesis = { statement: string }
export type GroundedCodeFinding = {
  category: CodeFindingCategory
  file_path: string
  line_number: number | null
  function_name: string | null
  statement: string
}
export type ProposedCodeFix = {
  finding_id: string
  file_path: string
  function_name: string | null
  line_start: number
  line_end: number
  original_hunk: string
  corrected_hunk: string
  failure_mechanism: string
  fix_strategy: string
  explanation: string
}
export type CodeFindingCategory =
  | 'changed_code_near_failure'
  | 'error_handling_or_null_path'
  | 'input_validation'
  | 'state_or_resource_lifecycle'
  | 'configuration_or_deployment'
export type DeveloperRecommendation = { message: string }
export type CorrelationIssue = {
  sentry_issue_id: string
  sentry_short_id: string
  jira_ticket: string | null
  commit_sha: string | null
  status: 'ok' | 'partial' | 'failed'
  step_failures: Array<{ step: string, failure_code: string }>
  presentation: {
    issue_title: string | null
    failure_file_path: string | null
    failure_line_number: number | null
    failure_function_name: string | null
    fact_summaries: FactSummary[]
    grounding_strength: 'strong' | 'moderate' | 'insufficient'
  }
  analysis: {
    status: 'insufficient_evidence' | 'hypothesis_generation_failed' | 'no_validated_hypothesis' | 'code_finding_unavailable' | 'completed' | 'analysis_error'
    hypotheses: GroundedHypothesis[]
    code_findings: GroundedCodeFinding[]
    recommendations: DeveloperRecommendation[]
    proposed_fixes: ProposedCodeFix[]
    fix_status: 'available' | 'unavailable'
  }
}
export type CorrelationScanResult = {
  repository_owner: string
  repository_name: string
  total_open_issues_found: number
  issues_scanned: number
  truncated: boolean
  results: CorrelationIssue[]
}

function isCorrelationScanResult(value: unknown): value is CorrelationScanResult {
  if (!isRecord(value) || !Array.isArray(value.results)) return false
  return typeof value.repository_owner === 'string'
    && typeof value.repository_name === 'string'
    && typeof value.total_open_issues_found === 'number'
    && typeof value.issues_scanned === 'number'
    && typeof value.truncated === 'boolean'
}

/** Submit the real, non-persisted repository correlation scan. */
export async function runCorrelationScan(request: CorrelationScanRequest): Promise<CorrelationScanResult> {
  const body = await requestJson('/v1/correlation-scans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!isCorrelationScanResult(body)) throw new ConnectorApiError('The API response is malformed.')
  return body
}
