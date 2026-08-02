/**
 * HTTP transport for connector inspection.
 *
 * This module knows URLs, HTTP methods, JSON encoding, and network errors. It
 * delegates response shape validation to responseValidation.ts and contains no
 * React state or rendering code.
 */

import { ConnectorApiError } from './apiError'
import {
  parseMergeReadiness,
  parseScenarioCatalog,
} from './responseValidation'
import type {
  ConnectorRequest,
  FixtureScenario,
  PullRequestMergeReadiness,
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
    // Expected API errors contain a top-level message. The fallback still gives
    // useful status information if an intermediary returns a different shape.
    const message =
      typeof body === 'object' &&
      body !== null &&
      'message' in body &&
      typeof body.message === 'string'
        ? body.message
        : `The API request failed with status ${response.status}.`

    throw new ConnectorApiError(message, response.status)
  }

  return body
}


export async function fetchFixtureScenarios(
  signal?: AbortSignal,
): Promise<FixtureScenario[]> {
  // The relative URL works through Vite's development proxy and through a
  // production same-origin router; browser code never hardcodes localhost.
  const body = await requestJson('/v1/demo/pull-request-scenarios', { signal })
  return parseScenarioCatalog(body)
}


export async function analyzePullRequestMergeReadiness(
  request: ConnectorRequest,
): Promise<PullRequestMergeReadiness> {
  const body = await requestJson('/v1/pull-request-merge-readiness', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

  return parseMergeReadiness(body)
}
