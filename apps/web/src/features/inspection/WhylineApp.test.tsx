import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { ProposedFixPanel, WhylineWorkspace } from './WhylineApp'
import type { ProposedCodeFix } from './api'


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
  expect(markup).toContain('Observed code')
  expect(markup).toContain(fix.original_hunk)
  expect(markup).toContain('Suggested correction')
  expect(markup).toContain(fix.corrected_hunk)
  expect(markup).toContain('Copy proposed fix')
  expect(markup).not.toContain('Apply')
  expect(markup).not.toContain('Push')
  expect(markup).not.toContain('Create PR')
})
