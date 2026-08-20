import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { InvestigationDashboard } from './InvestigationDashboard'
import type { InvestigationRun } from './types'


const RUN: InvestigationRun = {
  run_id: 'run-1',
  workflow_name: 'investigation',
  workflow_version: '2.19',
  status: 'completed',
  started_at: '2026-08-19T10:00:00Z',
  completed_at: '2026-08-19T10:00:01Z',
  steps: [],
  request: {
    repository_owner: 'octo-org',
    repository_name: 'analytics',
    incident_summary: 'Checkout failed.',
  },
  error: null,
  state: {
    rounds: [{
      round_number: 1,
      plan_id: 'round-1',
      plan_validation_status: 'accepted',
      steps: [{
        step_id: 's1',
        tool_id: 'get_incident',
        status: 'succeeded',
        attempts: 1,
        failure_code: null,
        failure_message: null,
        block_reason: null,
      }],
      evidence_delta_ids: ['E1'],
      fact_delta_ids: ['F1'],
      completed: true,
    }],
    evidence: [{
      evidence_id: 'E1',
      source: 'incident',
      kind: 'incident',
      provenance: {
        source_reference: 'incident:1',
        observed_at: null,
        retrieved_at: '2026-08-19T10:00:00Z',
      },
      content: { incident_reference: 'incident:1' },
    }],
    facts: [{ fact_id: 'F1', fact_type: 'stack_frame', evidence_reference_ids: ['E1'], file_path: 'checkout.py' }],
    missing_information: [],
    validated_hypotheses: [],
    rejected_hypothesis_count: 1,
    max_tool_calls: 10,
    used_tool_calls: 1,
    remaining_tool_calls: 9,
    termination_reason: 'provider_failure',
  },
  result: {
    termination_reason: 'provider_failure',
    summary: 'The investigation found relevant evidence, but it is not sufficient to support a causal hypothesis.',
    supported_hypotheses: [],
    key_fact_ids: [],
    missing_information: [],
  },
}


test('keeps timeline, Evidence, Facts, hypotheses, and grounded result separate', () => {
  const markup = renderToStaticMarkup(<InvestigationDashboard run={RUN} />)

  expect(markup).toContain('Investigation timeline')
  expect(markup).toContain('Normalized observations')
  expect(markup).toContain('Derived deterministic facts')
  expect(markup).toContain('Validated hypotheses')
  expect(markup).toContain('No supported causal hypothesis')
  expect(markup).toContain('provider failure')
  expect(markup).not.toContain('raw causal')
})


test('renders a budget stop separately from a failed or blocked tool state', () => {
  const run: InvestigationRun = {
    ...RUN,
    status: 'running',
    completed_at: null,
    result: null,
    state: {
      ...RUN.state,
      rounds: [{
        ...RUN.state.rounds[0],
        completed: false,
        steps: [
          { ...RUN.state.rounds[0].steps[0], status: 'failed', attempts: 2, failure_message: 'Timed out.' },
          { ...RUN.state.rounds[0].steps[0], step_id: 's2', tool_id: 'get_diff', status: 'blocked', attempts: 0, block_reason: 'budget_exhausted' },
        ],
      }],
      used_tool_calls: 10,
      remaining_tool_calls: 0,
      termination_reason: 'budget_exhausted',
    },
  }

  const markup = renderToStaticMarkup(<InvestigationDashboard run={run} />)

  expect(markup).toContain('10 / 10')
  expect(markup).toContain('Failed')
  expect(markup).toContain('Blocked')
  expect(markup).toContain('Attempt(s): 2')
  expect(markup).toContain('budget exhausted')
})


test('shows only validated hypotheses in the final grounded result', () => {
  const markup = renderToStaticMarkup(<InvestigationDashboard run={{
    ...RUN,
    state: {
      ...RUN.state,
      validated_hypotheses: [{
        hypothesis_id: 'H1',
        kind: 'code_change_may_have_contributed',
        subject: 'checkout.py',
        supporting_fact_ids: ['F1'],
      }],
    },
    result: {
      ...RUN.result!,
      supported_hypotheses: [{
        hypothesis_id: 'H1',
        kind: 'code_change_may_have_contributed',
        subject: 'checkout.py',
        statement: 'Changes associated with checkout.py may have contributed to the incident.',
        supporting_fact_ids: ['F1'],
      }],
    },
  }} />)

  expect(markup).toContain('Likely contributing factor')
  expect(markup).toContain('Changes associated with checkout.py may have contributed')
  expect(markup).not.toContain('provider rationale')
})
