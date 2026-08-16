import { afterEach, describe, expect, test } from 'bun:test'
import {
  analyzePullRequestMergeReadiness,
  fetchMergeReadinessRun,
  startLiveMergeReadinessRun,
} from './api'
import { ConnectorApiError } from './apiError'
import type { PullRequestMergeReadiness } from './types'


const READY_RESPONSE: PullRequestMergeReadiness = {
  run_id: '49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
  workflow_name: 'merge_readiness',
  workflow_version: '1',
  sources: { github: 'fake', jira: 'fake', explanation: 'fake' },
  status: 'completed',
  started_at: '2026-08-02T10:00:00Z',
  completed_at: '2026-08-02T10:00:01Z',
  steps: [],
  error: null,
  request: {
    repository_owner: 'acme',
    repository_name: 'analytics',
    pr_number: 1,
  },
  github: null,
  jira: null,
  result: {
    decision: 'ready',
    summary: 'All required conditions are satisfied.',
    reason_code: 'ready',
    blockers: [],
    pending_actions: [],
    missing_information: [],
    evidence_references: [],
  },
  explanation: {
    decision: 'ready',
    summary: 'The deterministic policy found the pull request ready.',
    reasons: ['All required merge-readiness evidence is satisfied.'],
    recommended_actions: [],
  },
  explanation_error: null,
}


const originalFetch = globalThis.fetch

const RUNNING_RESPONSE = {
  ...READY_RESPONSE,
  status: 'running' as const,
  started_at: '2026-08-02T10:00:00Z',
  completed_at: null,
  steps: [
    {
      step_id: 'c3bdb98c-1389-4eb8-a8bb-b004b323dd64',
      name: 'fetch_github_facts' as const,
      status: 'running' as const,
      started_at: '2026-08-02T10:00:00Z',
      completed_at: null,
      duration_ms: null,
      attempt: 1,
      error: null,
    },
  ],
  error: null,
  result: null,
  explanation: null,
  explanation_error: null,
}

const PENDING_RESPONSE = {
  ...RUNNING_RESPONSE,
  status: 'pending' as const,
  started_at: null,
  steps: [],
}


afterEach(() => {
  globalThis.fetch = originalFetch
})


describe('merge-readiness API client', () => {
  test('starts a live run through the additive accepted-work endpoint', async () => {
    let requestedUrl = ''
    let requestedInit: RequestInit | undefined
    globalThis.fetch = (async (url, init) => {
      requestedUrl = String(url)
      requestedInit = init
      return new Response(
        JSON.stringify({ run_id: READY_RESPONSE.run_id, status: 'pending' }),
        { status: 202, headers: { 'Content-Type': 'application/json' } },
      )
    }) as typeof fetch

    const accepted = await startLiveMergeReadinessRun(READY_RESPONSE.request)

    expect(requestedUrl).toBe('/v1/pull-request-merge-readiness-runs')
    expect(requestedInit?.method).toBe('POST')
    expect(accepted).toEqual({ run_id: READY_RESPONSE.run_id, status: 'pending' })
  })

  test('parses a current running snapshot retrieved by run ID', async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify(RUNNING_RESPONSE), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })) as typeof fetch

    const run = await fetchMergeReadinessRun(READY_RESPONSE.run_id)

    expect(run.status).toBe('running')
    expect(run.completed_at).toBeNull()
    expect(run.steps[0]?.status).toBe('running')
  })

  test('parses a valid pending run before its first step starts', async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify(PENDING_RESPONSE), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })) as typeof fetch

    const run = await fetchMergeReadinessRun(READY_RESPONSE.run_id)

    expect(run.status).toBe('pending')
    expect(run.started_at).toBeNull()
    expect(run.steps).toEqual([])
  })

  test('rejects malformed live snapshots before dashboard rendering', async () => {
    globalThis.fetch = (async () =>
      new Response(
        JSON.stringify({ ...RUNNING_RESPONSE, result: READY_RESPONSE.result }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )) as typeof fetch

    await expect(fetchMergeReadinessRun(READY_RESPONSE.run_id)).rejects.toMatchObject({
      name: 'ConnectorApiError',
      message: 'The merge-readiness response is malformed.',
    } satisfies Partial<ConnectorApiError>)
  })

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
    expect(result.result.decision).toBe('ready')
  })

  test('keeps backend failures separate from an unknown policy decision', async () => {
    const failedResponse: PullRequestMergeReadiness = {
      ...READY_RESPONSE,
      status: 'failed',
      result: null,
      error: {
        code: 'connector_execution_failed',
        message: 'The GitHub connector step failed unexpectedly.',
      },
      explanation: null,
      explanation_error: null,
    }
    globalThis.fetch = (async () =>
      new Response(JSON.stringify(failedResponse), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      })) as typeof fetch

    const result = await analyzePullRequestMergeReadiness(READY_RESPONSE.request)

    expect(result.status).toBe('failed')
    if (result.status === 'failed') {
      expect(result.error.code).toBe('connector_execution_failed')
      expect(result.result).toBeNull()
    }
  })

  test('rejects an explanation that changes the backend policy decision', async () => {
    globalThis.fetch = (async () =>
      new Response(
        JSON.stringify({
          ...READY_RESPONSE,
          explanation: {
            ...READY_RESPONSE.explanation,
            decision: 'blocked',
          },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      )) as typeof fetch

    await expect(
      analyzePullRequestMergeReadiness(READY_RESPONSE.request),
    ).rejects.toMatchObject({
      name: 'ConnectorApiError',
      message: 'The merge-readiness response is malformed.',
    } satisfies Partial<ConnectorApiError>)
  })

  test('accepts an older completed response without source provenance', async () => {
    const { sources: _sources, ...olderResponse } = READY_RESPONSE
    globalThis.fetch = (async () =>
      new Response(JSON.stringify(olderResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })) as typeof fetch

    const result = await analyzePullRequestMergeReadiness(READY_RESPONSE.request)

    expect(result.sources).toBeNull()
  })

  test('accepts Groq as a bounded explanation source', async () => {
    globalThis.fetch = (async () =>
      new Response(
        JSON.stringify({
          ...READY_RESPONSE,
          sources: {
            ...READY_RESPONSE.sources,
            explanation: 'groq',
          },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      )) as typeof fetch

    const result = await analyzePullRequestMergeReadiness(
      READY_RESPONSE.request,
    )

    expect(result.sources?.explanation).toBe('groq')
  })

  test('rejects unbounded source identities', async () => {
    globalThis.fetch = (async () =>
      new Response(
        JSON.stringify({
          ...READY_RESPONSE,
          sources: {
            ...READY_RESPONSE.sources,
            github: 'github-enterprise',
          },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      )) as typeof fetch

    await expect(
      analyzePullRequestMergeReadiness(READY_RESPONSE.request),
    ).rejects.toMatchObject({
      name: 'ConnectorApiError',
      message: 'The merge-readiness response is malformed.',
    } satisfies Partial<ConnectorApiError>)
  })
})
