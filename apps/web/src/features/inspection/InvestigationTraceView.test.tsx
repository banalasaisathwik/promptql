import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  FactChainPanel,
  TraceEventList,
  TraceResultBanner,
  TraceRoundSidebar,
} from './InvestigationTraceView'
import type { InvestigationPlanningRound, LiveRunEvent } from './types'


const TOOL_CALL_EVENT: LiveRunEvent = {
  event: 'investigation.tool.call_completed',
  level: 'info',
  timestamp: '2026-08-02T10:00:00Z',
  run_id: '49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
  fields: { tool_id: 'get_incident', tool_outcome: 'observed' },
}


test('shows an empty state before any event arrives', () => {
  const markup = renderToStaticMarkup(<TraceEventList events={[]} status="connecting" />)

  expect(markup).toContain('No events received yet.')
  expect(markup).toContain('Connecting')
})


test('renders each received event as a streaming log line with its semantic tag and fields', () => {
  const markup = renderToStaticMarkup(
    <TraceEventList events={[TOOL_CALL_EVENT]} status="open" streaming />,
  )

  expect(markup).toContain('investigation.tool.call_completed')
  expect(markup).toContain('tool_id=get_incident')
  expect(markup).toContain('trace-log-tag--tool')
  expect(markup).toContain('streaming')
  expect(markup).toContain('trace-cursor')
})


test('renders persisted planning rounds as the left-hand checklist', () => {
  const rounds: InvestigationPlanningRound[] = [{
    round_number: 1,
    plan_id: 'round-1',
    plan_validation_status: 'accepted',
    completed: true,
    evidence_delta_ids: [],
    fact_delta_ids: [],
    steps: [{
      step_id: 'step-1',
      tool_id: 'get_diff',
      status: 'succeeded',
      attempts: 1,
      failure_code: null,
      failure_message: null,
      block_reason: null,
    }],
  }]

  const markup = renderToStaticMarkup(<TraceRoundSidebar rounds={rounds} />)

  expect(markup).toContain('Round 1')
  expect(markup).toContain('complete')
  expect(markup).toContain('get_diff')
  expect(markup).toContain('trace-round-step--succeeded')
})


test('renders only a backend-grounded connected fact chain', () => {
  const markup = renderToStaticMarkup(<FactChainPanel chain={['F-deploy', 'F-commit']} />)

  expect(markup).toContain('Fact chain forming')
  expect(markup).toContain('F-deploy')
  expect(markup).toContain('F-commit')
  expect(markup).toContain('trace-chain-node--active')
})


test('links to the run dashboard once the investigation reaches a terminal state', () => {
  const markup = renderToStaticMarkup(
    <TraceResultBanner runId="49a8a46d-5c69-4e5d-a928-6a149b84d6e7" status="completed" />,
  )

  expect(markup).toContain('href="/runs/49a8a46d-5c69-4e5d-a928-6a149b84d6e7"')
  expect(markup).toContain('View full result')
  expect(markup).toContain('trace-result-banner--completed')
})


test('shows nothing while the investigation is still running', () => {
  const markup = renderToStaticMarkup(
    <TraceResultBanner runId="49a8a46d-5c69-4e5d-a928-6a149b84d6e7" status="running" />,
  )

  expect(markup).toBe('')
})
