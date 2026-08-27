/**
 * HTTP transport for connector inspection.
 *
 * This module knows URLs, HTTP methods, JSON encoding, and network errors. It
 * delegates response shape validation to responseValidation.ts and contains no
 * React state or rendering code.
 */

import { ConnectorApiError } from './apiError'
import {
  parseGroundingExtractionResponse,
  parseLiveRunStart,
  parseRuntimeRun,
} from './responseValidation'
import type {
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
    response = await fetch(url, init)
  } catch {
    // Browser fetch throws for network failures, not for HTTP 404/500 statuses.
    throw new ConnectorApiError(
      'Could not reach the API. Confirm that the backend server is running.',
    )
  }

  const body = await readJson(response)

  if (!response.ok) {
    let message = `The API request failed with status ${response.status}.`
    if (
      typeof body === 'object' &&
      body !== null &&
      'message' in body &&
      typeof body.message === 'string'
    ) {
      message = body.message
    } else if (
      typeof body === 'object' &&
      body !== null &&
      'error' in body &&
      typeof body.error === 'object' &&
      body.error !== null &&
      'message' in body.error &&
      typeof body.error.message === 'string'
    ) {
      // Failed runs contain a sanitized error nested inside the run body.
      message = body.error.message
    }

    throw new ConnectorApiError(message, response.status)
  }

  return body
}


async function requestMergeReadiness(
  url: string,
  init: RequestInit,
): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(url, init)
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

  let message = `The API request failed with status ${response.status}.`
  if (
    typeof body === 'object' &&
    body !== null &&
    'message' in body &&
    typeof body.message === 'string'
  ) {
    message = body.message
  }
  throw new ConnectorApiError(message, response.status)
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
  })
  return parseGroundingExtractionResponse(body)
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
