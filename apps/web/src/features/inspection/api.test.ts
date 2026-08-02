import { afterEach, describe, expect, test } from 'bun:test'
import { analyzePullRequestMergeReadiness } from './api'
import { ConnectorApiError } from './apiError'
import type { PullRequestMergeReadiness } from './types'


const READY_RESPONSE: PullRequestMergeReadiness = {
  request: {
    repository_owner: 'acme',
    repository_name: 'analytics',
    pr_number: 1,
  },
  github: null,
  jira: null,
  policy_result: {
    decision: 'ready',
    summary: 'All required conditions are satisfied.',
    reason_code: 'ready',
    blockers: [],
    pending_actions: [],
    missing_information: [],
    evidence_references: [],
  },
}


const originalFetch = globalThis.fetch


afterEach(() => {
  globalThis.fetch = originalFetch
})


describe('merge-readiness API client', () => {
  test('submits the exact request fields to the complete workflow endpoint', async () => {
    let requestedUrl = ''
    let requestedInit: RequestInit | undefined

    globalThis.fetch = (async (url, init) => {
      requestedUrl = String(url)
      requestedInit = init
      return new Response(JSON.stringify(READY_RESPONSE), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }) as typeof fetch

    const request = {
      repository_owner: 'acme',
      repository_name: 'analytics',
      pr_number: 3,
    }
    const result = await analyzePullRequestMergeReadiness(request)

    expect(requestedUrl).toBe('/v1/pull-request-merge-readiness')
    expect(requestedInit?.method).toBe('POST')
    expect(JSON.parse(String(requestedInit?.body))).toEqual(request)
    expect(result.policy_result.decision).toBe('ready')
  })

  test('keeps backend failures separate from an unknown policy decision', async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ message: 'Connector failed.' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      })) as typeof fetch

    await expect(
      analyzePullRequestMergeReadiness(READY_RESPONSE.request),
    ).rejects.toBeInstanceOf(ConnectorApiError)
  })
})
