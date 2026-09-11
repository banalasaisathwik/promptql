import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { Diagnosis, IssueCard, ProposedFixPanel, WhylineWorkspace } from './WhylineApp'
import type { CorrelationIssue, ProposedCodeFix } from './api'


test('repository scan exposes two compact discovery comboboxes, not manual identifiers', () => {
  const markup = renderToStaticMarkup(
    <WhylineWorkspace
      user={{
        id: 'a9e3c5d3-c089-4b5e-a006-63f1a3e66a3a',
        email: 'user@example.com',
        created_at: '2026-09-11T10:00:00Z',
      }}
      page="scan"
      navigate={() => undefined}
      onLogout={() => undefined}
    />,
  )

  expect(markup).toContain('Repository')
  expect(markup).toContain('Sentry project')
  expect(markup).toContain('Analyze repository')
  expect(markup).toContain('Repository Scan')
  expect(markup).toContain('Sources')
  expect(markup).not.toContain('Search repositories')
  expect(markup).not.toContain('Search Sentry projects')
  expect(markup).not.toContain('<select')
  expect(markup).not.toContain('Repository owner')
  expect(markup).not.toContain('Repository name')
})

test('proposed fix panel shows failure mechanism, fix strategy, and both hunks, never an apply/push action', () => {
  const fix: ProposedCodeFix = {
    finding_id: 'finding:decrement-inventory',
    file_path: 'sandbox-target/app/checkout.py',
    function_name: 'decrement_inventory',
    line_start: 4,
    line_end: 16,
    original_hunk: 'STOCK[item_id - 1] -= qty',
    corrected_hunk: 'STOCK[item_id] -= qty',
    failure_mechanism: 'The write uses an off-by-one index into STOCK.',
    fix_strategy: 'Align the write with the read so both use item_id.',
    explanation: 'This removes the KeyError without touching unrelated code.',
  }

  const markup = renderToStaticMarkup(<ProposedFixPanel fix={fix} />)

  expect(markup).toContain('Proposed fix')
  expect(markup).toContain('Failure mechanism')
  expect(markup).toContain(fix.failure_mechanism)
  expect(markup).toContain('Fix strategy')
  expect(markup).toContain(fix.fix_strategy)
  expect(markup).toContain('Patch')
  expect(markup).toContain(fix.original_hunk)
  expect(markup).toContain(fix.corrected_hunk)
  expect(markup).toContain('Why this fixes it')
  expect(markup).toContain(fix.explanation)
  expect(markup).toContain('Copy patch')
  expect(markup).not.toContain('Apply')
  expect(markup).not.toContain('Push')
  expect(markup).not.toContain('Create PR')
})

function fixtureIssue(overrides: Partial<CorrelationIssue> = {}): CorrelationIssue {
  return {
    sentry_issue_id: '1',
    sentry_short_id: 'PYTHON-FASTAPI-1',
    jira_ticket: null,
    commit_sha: 'e1448f6abc123',
    status: 'ok',
    step_failures: [],
    presentation: {
      issue_title: 'KeyError: 0',
      failure_file_path: '/opt/render/project/src/sandbox-target/app/checkout.py',
      failure_line_number: 13,
      failure_function_name: 'decrement_inventory',
      fact_summaries: [{ label: 'Changed file matches failure file', detail: null }],
      grounding_strength: 'strong',
    },
    analysis: {
      status: 'completed',
      hypotheses: [{ statement: 'Changes associated with decrement_inventory may have contributed to the incident.' }],
      code_findings: [
        {
          category: 'changed_code_near_failure',
          file_path: '/opt/render/project/src/sandbox-target/app/checkout.py',
          line_number: 13,
          function_name: 'decrement_inventory',
          statement: 'The evidence identifies changed code near the observed failure at app/checkout.py in decrement_inventory at line 13 as a suspected contributor.',
        },
        {
          category: 'changed_code_near_failure',
          file_path: '/opt/render/project/src/sandbox-target/app/checkout.py',
          line_number: 13,
          function_name: 'decrement_inventory',
          statement: 'Duplicate evidence for the same finding.',
        },
      ],
      recommendations: [],
      proposed_fixes: [
        {
          finding_id: 'finding:decrement-inventory',
          file_path: '/opt/render/project/src/sandbox-target/app/checkout.py',
          function_name: 'decrement_inventory',
          line_start: 13,
          line_end: 13,
          original_hunk: 'STOCK[item_id - 1] -= qty',
          corrected_hunk: 'STOCK[item_id] -= qty',
          failure_mechanism: 'The write uses an off-by-one index into STOCK.',
          fix_strategy: 'Align the write with the read so both use item_id.',
          explanation: 'This removes the KeyError without touching unrelated code.',
        },
      ],
      fix_status: 'available',
    },
    ...overrides,
  }
}

test('diagnosis presents the repository-relative path instead of the absolute sandbox path', () => {
  const markup = renderToStaticMarkup(
    <Diagnosis issue={fixtureIssue()} repositoryName="sandbox-target" onBack={() => undefined} />,
  )

  expect(markup).toContain('app/checkout.py')
  expect(markup).not.toContain('/opt/render/project/src/sandbox-target')
})

test('diagnosis collapses duplicate code findings into one card with an evidence count', () => {
  const markup = renderToStaticMarkup(
    <Diagnosis issue={fixtureIssue()} repositoryName="sandbox-target" onBack={() => undefined} />,
  )

  expect(markup).toContain('Supported by 2 evidence items')
  expect(markup.match(/The evidence identifies changed code near the observed failure/g)?.length).toBe(1)
  expect(markup).not.toContain('Duplicate evidence for the same finding.')
})

test('diagnosis shows a one-line failure summary built from the hypothesis and fix strategy', () => {
  const markup = renderToStaticMarkup(
    <Diagnosis issue={fixtureIssue()} repositoryName="sandbox-target" onBack={() => undefined} />,
  )

  expect(markup).toContain('Changes associated with decrement_inventory may have contributed to the incident.')
  expect(markup).toContain('Align the write with the read so both use item_id.')
})

test('diagnosis renders the sticky sidebar with compact failure-location metadata, not repeated prose', () => {
  const markup = renderToStaticMarkup(
    <Diagnosis issue={fixtureIssue()} repositoryName="sandbox-target" onBack={() => undefined} />,
  )

  expect(markup).toContain('Diagnosis')
  expect(markup).toContain('Failure location')
  expect(markup).toContain('Line 13')
})

test('issue card shows the repository-relative failure location', () => {
  const markup = renderToStaticMarkup(
    <IssueCard issue={fixtureIssue()} repositoryName="sandbox-target" onView={() => undefined} />,
  )

  expect(markup).toContain('app/checkout.py')
  expect(markup).not.toContain('/opt/render/project/src/sandbox-target')
})
