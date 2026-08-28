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
    question: 'Why did checkout fail?',
  },
  error: null,
  state: {
    working_memory: {
      evidence: ['E1'],
      evidence_content: [{
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
      validated_code_findings: [],
      developer_recommendations: [],
      action_history: [{
        tool_id: 'get_incident',
        outcome: 'observed',
        produced_new_evidence: true,
        produced_new_facts: true,
      }],
    },
    execution_state: {
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
      hypothesis_generation_metadata: null,
      rejected_hypothesis_count: 1,
      code_diagnosis_metadata: null,
      rejected_code_finding_count: 0,
      max_tool_calls: 10,
      used_tool_calls: 1,
      remaining_tool_calls: 9,
      termination_reason: 'provider_failure',
    },
  },
  results: [{
    termination_reason: 'provider_failure',
    summary: 'The investigation found relevant evidence, but it is not sufficient to support a causal hypothesis.',
    supported_hypotheses: [],
    code_findings: [],
    recommendations: [],
    key_fact_ids: [],
    missing_information: [],
  }],
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
    results: [],
    state: {
      ...RUN.state,
      execution_state: {
        ...RUN.state!.execution_state,
        rounds: [{
          ...RUN.state!.execution_state.rounds[0],
          completed: false,
          steps: [
            { ...RUN.state!.execution_state.rounds[0].steps[0], status: 'failed', attempts: 2, failure_message: 'Timed out.' },
            { ...RUN.state!.execution_state.rounds[0].steps[0], step_id: 's2', tool_id: 'get_diff', status: 'blocked', attempts: 0, block_reason: 'budget_exhausted' },
          ],
        }],
        used_tool_calls: 10,
        remaining_tool_calls: 0,
        termination_reason: 'budget_exhausted',
      },
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
      working_memory: {
        ...RUN.state!.working_memory,
        validated_hypotheses: [{
          hypothesis_id: 'H1',
          kind: 'code_change_may_have_contributed',
          subject: 'checkout.py',
          supporting_fact_ids: ['F1'],
        }],
      },
    },
    results: [{
      ...RUN.results[0],
      supported_hypotheses: [{
        hypothesis_id: 'H1',
        kind: 'code_change_may_have_contributed',
        subject: 'checkout.py',
        statement: 'Changes associated with checkout.py may have contributed to the incident.',
        supporting_fact_ids: ['F1'],
      }],
    }],
  }} />)

  expect(markup).toContain('Likely contributing factor')
  expect(markup).toContain('Changes associated with checkout.py may have contributed')
  expect(markup).not.toContain('provider rationale')
})


test('projects only backend-validated code locations and recommendations', () => {
  const codeFinding = {
    finding_id: 'CF1',
    hypothesis_id: 'H1',
    file_path: 'checkout.py',
    line_number: 42,
    function_name: 'submit_order',
    hunk_evidence_id: 'E2',
    category: 'error_handling',
    supporting_fact_ids: ['F1'],
    supporting_evidence_ids: ['E1', 'E2'],
  }
  const recommendation = {
    recommendation_id: 'REC-CF1-1',
    code: 'validate_error_handling',
    message: 'Verify the error-handling path at the validated location.',
    finding_id: 'CF1',
    supporting_fact_ids: ['F1'],
    supporting_evidence_ids: ['E1', 'E2'],
  }
  const markup = renderToStaticMarkup(<InvestigationDashboard run={{
    ...RUN,
    state: {
      ...RUN.state,
      working_memory: {
        ...RUN.state!.working_memory,
        validated_code_findings: [codeFinding],
        developer_recommendations: [recommendation],
      },
    },
    results: [{
      ...RUN.results[0],
      code_findings: [{
        ...codeFinding,
        statement: 'The validated evidence identifies an error handling concern at checkout.py:42.',
      }],
      recommendations: [recommendation],
    }],
  }} />)

  expect(markup).toContain('Validated code findings')
  expect(markup).toContain('checkout.py:42 in submit_order')
  expect(markup).toContain('The validated evidence identifies an error handling concern')
  expect(markup).toContain('Verify the error-handling path at the validated location.')
  expect(markup).not.toContain('provider code rationale')
})


test('renders each follow-up result as a growing thread below the original result', () => {
  const followUpResult = {
    termination_reason: 'goal_satisfied',
    summary: 'The deployment introduced the regression the first result already pointed to.',
    supported_hypotheses: [],
    code_findings: [],
    recommendations: [],
    key_fact_ids: [],
    missing_information: [],
  }
  const run: InvestigationRun = { ...RUN, results: [RUN.results[0], followUpResult] }

  const markup = renderToStaticMarkup(<InvestigationDashboard run={run} />)

  expect(markup).toContain('Original investigation result')
  expect(markup).toContain(RUN.results[0].summary)
  expect(markup).toContain('Follow-up result 1')
  expect(markup).toContain(followUpResult.summary)
  // The original result must still render fully, ahead of the follow-up
  // result, rather than being replaced by it.
  expect(markup.indexOf('Original investigation result')).toBeLessThan(
    markup.indexOf('Follow-up result 1'),
  )
})


test('offers the follow-up form only once the investigation has completed', () => {
  const runningMarkup = renderToStaticMarkup(
    <InvestigationDashboard run={{ ...RUN, status: 'running', completed_at: null, results: [] }} />,
  )
  const completedMarkup = renderToStaticMarkup(<InvestigationDashboard run={RUN} />)

  expect(runningMarkup).not.toContain('Ask a follow-up')
  expect(completedMarkup).toContain('Ask a follow-up')
})
