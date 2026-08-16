import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { RunDashboard } from './RunDashboardPage'
import type { PullRequestMergeReadiness } from './types'


const RUNNING_RUN: PullRequestMergeReadiness = {
  run_id: '49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
  workflow_name: 'merge_readiness',
  workflow_version: '1',
  sources: { github: 'live', jira: 'fake', explanation: 'groq' },
  status: 'running',
  started_at: '2026-08-02T10:00:00Z',
  completed_at: null,
  steps: [
    {
      step_id: 'c3bdb98c-1389-4eb8-a8bb-b004b323dd64',
      name: 'fetch_github_facts',
      status: 'completed',
      started_at: '2026-08-02T10:00:00Z',
      completed_at: '2026-08-02T10:00:00.420Z',
      duration_ms: 420,
      attempt: 1,
      error: null,
    },
    {
      step_id: '5a9590f9-0f1d-4c6f-9e53-6e71b7c7c781',
      name: 'fetch_jira_facts',
      status: 'running',
      started_at: '2026-08-02T10:00:00.420Z',
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
  request: { repository_owner: 'acme', repository_name: 'analytics', pr_number: 1 },
  github: null,
  jira: null,
}


test('renders current activity, readable ordered steps, timings, sources, and validated raw JSON', () => {
  const markup = renderToStaticMarkup(<RunDashboard run={RUNNING_RUN} />)

  expect(markup).toContain('Fetch Jira facts')
  expect(markup).toContain('Fetch GitHub facts')
  expect(markup).toContain('420 ms')
  expect(markup).toContain('GitHub')
  expect(markup).toContain('groq')
  expect(markup).toContain('Raw Run')
  expect(markup).toContain(RUNNING_RUN.run_id)
})


test('renders pending as waiting to start instead of inventing a running step', () => {
  const pending: PullRequestMergeReadiness = {
    ...RUNNING_RUN,
    status: 'pending',
    started_at: null,
    steps: [],
  }

  const markup = renderToStaticMarkup(<RunDashboard run={pending} />)

  expect(markup).toContain('Waiting to start')
  expect(markup).toContain('0 recorded')
})


test('renders a sanitized failed run without inventing a policy result', () => {
  const failed: PullRequestMergeReadiness = {
    ...RUNNING_RUN,
    status: 'failed',
    completed_at: '2026-08-02T10:00:01Z',
    error: {
      code: 'connector_execution_failed',
      message: 'The GitHub connector step failed unexpectedly.',
    },
  }
  const markup = renderToStaticMarkup(<RunDashboard run={failed} />)

  expect(markup).toContain('connector_execution_failed')
  expect(markup).not.toContain('Overall decision')
})
