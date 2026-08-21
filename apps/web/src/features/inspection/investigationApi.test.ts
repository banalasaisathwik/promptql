import { afterEach, expect, test } from 'bun:test'
import { fetchRuntimeRun, startInvestigationRun } from './api'


const originalFetch = globalThis.fetch


afterEach(() => {
  globalThis.fetch = originalFetch
})


test('submits structured investigation input through the live-start API', async () => {
  let requestBody = ''
  globalThis.fetch = (async (_url, init) => {
    requestBody = String(init?.body)
    return new Response(JSON.stringify({ run_id: 'run-1', status: 'pending' }), { status: 202 })
  }) as typeof fetch

  const request = {
    repository_owner: 'octo-org',
    repository_name: 'analytics',
    question: 'Why did checkout fail?',
    incident_reference: 'incident:checkout-500',
  }
  await startInvestigationRun(request)

  expect(JSON.parse(requestBody)).toEqual(request)
})


test('parses a pending investigation snapshot through the shared run route', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({
    run_id: 'run-1',
    workflow_name: 'investigation',
    workflow_version: '2.19',
    status: 'pending',
    started_at: null,
    completed_at: null,
    steps: [],
    request: {
      repository_owner: 'octo-org',
      repository_name: 'analytics',
      question: 'Why did checkout fail?',
    },
    error: null,
    state: null,
    result: null,
  }), { status: 200 })) as typeof fetch

  const run = await fetchRuntimeRun('run-1')

  expect(run.workflow_name).toBe('investigation')
  expect(run.status).toBe('pending')
})
