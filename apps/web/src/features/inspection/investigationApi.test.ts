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
    result: null,
  }), { status: 200 })) as typeof fetch

  await expect(fetchRuntimeRun('run-1')).rejects.toThrow('response is malformed')
})
