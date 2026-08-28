import { afterEach, expect, test } from 'bun:test'
import { fetchRuntimeRun, startInvestigationFollowUp, startInvestigationRun } from './api'
import { ConnectorApiError } from './apiError'


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
    results: [],
  }), { status: 200 })) as typeof fetch

  const run = await fetchRuntimeRun('run-1')

  expect(run.workflow_name).toBe('investigation')
  expect(run.status).toBe('pending')
})


test('rejects a completed snapshot with an unvalidated code-location shape', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({
    run_id: 'run-1',
    workflow_name: 'investigation',
    workflow_version: '2.19.2',
    status: 'completed',
    started_at: '2026-08-21T10:00:00Z',
    completed_at: '2026-08-21T10:00:01Z',
    steps: [],
    request: {
      repository_owner: 'octo-org',
      repository_name: 'analytics',
      question: 'Why did checkout fail?',
    },
    error: null,
    state: {
      working_memory: {
        evidence: [], evidence_content: [], facts: [], missing_information: [],
        validated_hypotheses: [],
        validated_code_findings: [{
          finding_id: 'CF1', hypothesis_id: 'H1', file_path: 'checkout.py',
          line_number: '42', function_name: null, hunk_evidence_id: null,
          category: 'error_handling', supporting_fact_ids: [], supporting_evidence_ids: [],
        }],
        developer_recommendations: [], action_history: [],
      },
      execution_state: {
        rounds: [], hypothesis_generation_metadata: null, rejected_hypothesis_count: 0,
        code_diagnosis_metadata: null, rejected_code_finding_count: 0,
        max_tool_calls: 10, used_tool_calls: 1,
        remaining_tool_calls: 9, termination_reason: 'completed',
      },
    },
    results: [],
  }), { status: 200 })) as typeof fetch

  await expect(fetchRuntimeRun('run-1')).rejects.toThrow('response is malformed')
})


test('submits a follow-up question through the reopen endpoint', async () => {
  let requestUrl = ''
  let requestBody = ''
  globalThis.fetch = (async (url, init) => {
    requestUrl = String(url)
    requestBody = String(init?.body)
    return new Response(JSON.stringify({ run_id: 'run-1', status: 'running' }), { status: 202 })
  }) as typeof fetch

  const accepted = await startInvestigationFollowUp('run-1', 'What about the deployment?')

  expect(requestUrl).toBe('/v1/investigations/run-1/follow-up')
  expect(JSON.parse(requestBody)).toEqual({ question: 'What about the deployment?' })
  expect(accepted).toEqual({ run_id: 'run-1', status: 'running' })
})


test('surfaces the backend follow-up-limit message on a 409 conflict', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({
    code: 'runtime_state_conflict',
    message: 'This investigation has reached its follow-up limit.',
    run_id: 'run-1',
  }), { status: 409 })) as typeof fetch

  await expect(startInvestigationFollowUp('run-1', 'Anything else?')).rejects.toMatchObject({
    message: 'This investigation has reached its follow-up limit.',
    status: 409,
  })
})


test('surfaces a 404 for a follow-up against an unknown run', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({
    code: 'run_not_found',
    message: 'No investigation exists for this ID.',
  }), { status: 404 })) as typeof fetch

  const error = await startInvestigationFollowUp('missing-run', 'Anything else?').catch((caught) => caught)

  expect(error).toBeInstanceOf(ConnectorApiError)
  expect(error.message).toBe('No investigation exists for this ID.')
  expect(error.status).toBe(404)
})
