import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { TraceEventList } from './InvestigationTraceView'
import type { LiveRunEvent } from './types'


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


test('renders each received event with its name, time, level, and fields', () => {
  const markup = renderToStaticMarkup(
    <TraceEventList events={[TOOL_CALL_EVENT]} status="open" />,
  )

  expect(markup).toContain('investigation.tool.call_completed')
  expect(markup).toContain('info')
  expect(markup).toContain('tool_id')
  expect(markup).toContain('get_incident')
  expect(markup).toContain('1 received')
})
