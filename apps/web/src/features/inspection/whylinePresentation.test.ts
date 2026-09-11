import { expect, test } from 'bun:test'
import { ConnectorApiError } from './apiError'
import type { CorrelationIssue, GroundedCodeFinding } from './api'
import {
  groupCodeFindings, whylineAnalysisLabel, whylineCategoryLabel, whylineDiscoveryErrorMessage,
  whylineErrorMessage, whylineFailureSummary, whylineGroundingLabel, whylineLocationParts,
  whylineScanErrorMessage,
} from './whylinePresentation'

test('maps scan errors without overwriting auth and credential error messages', () => {
  expect(whylineErrorMessage(new ConnectorApiError('An account with this email already exists.', 409))).toBe('An account with this email already exists.')
  expect(whylineScanErrorMessage(new ConnectorApiError('raw', 409))).toBe('Required source is not connected.')
  expect(whylineScanErrorMessage(new ConnectorApiError('raw', 422))).toBe('Check the entered values.')
  expect(whylineScanErrorMessage(new ConnectorApiError('raw', 503))).toBe('A connected provider is temporarily unavailable.')
  expect(whylineDiscoveryErrorMessage('GitHub', new ConnectorApiError('raw', 503))).toBe('GitHub is temporarily unavailable. Try again.')
  expect(whylineDiscoveryErrorMessage('Sentry', new ConnectorApiError('raw', 409))).toBe('Connect Sentry to choose a project.')
})

test('preserves the backend analysis distinction in user-facing labels', () => {
  expect(whylineAnalysisLabel('completed')).toBe('Grounded')
  expect(whylineAnalysisLabel('insufficient_evidence')).toBe('Insufficient evidence')
  expect(whylineAnalysisLabel('no_validated_hypothesis')).toBe('No grounded hypothesis')
  expect(whylineAnalysisLabel('code_finding_unavailable')).toContain('code location unavailable')
})

test('renders validated taxonomy and deterministic grounding as readable labels', () => {
  expect(whylineCategoryLabel('error_handling_or_null_path')).toBe('Error handling / invalid state')
  expect(whylineGroundingLabel('strong')).toBe('Strong grounding')
  expect(whylineGroundingLabel('insufficient')).toBe('Insufficient evidence')
})

test('whylineLocationParts includes only the pieces that are present', () => {
  expect(whylineLocationParts('app/checkout.py', 13, 'decrement_inventory')).toEqual([
    'app/checkout.py',
    'Line 13',
    'decrement_inventory()',
  ])
  expect(whylineLocationParts(null, null, null)).toEqual([])
  expect(whylineLocationParts('app/checkout.py', null, null)).toEqual(['app/checkout.py'])
})

test('whylineLocationParts normalizes an absolute path to the repository-relative path', () => {
  expect(
    whylineLocationParts(
      '/opt/render/project/src/sandbox-target/app/checkout.py',
      13,
      null,
      'sandbox-target',
    ),
  ).toEqual(['app/checkout.py', 'Line 13'])
})

function issueWithAnalysis(analysis: Partial<CorrelationIssue['analysis']>): CorrelationIssue {
  return {
    sentry_issue_id: '1',
    sentry_short_id: 'PYTHON-FASTAPI-1',
    jira_ticket: null,
    commit_sha: 'e1448f6abc',
    status: 'ok',
    step_failures: [],
    presentation: {
      issue_title: 'KeyError: 0',
      failure_file_path: 'app/checkout.py',
      failure_line_number: 13,
      failure_function_name: 'decrement_inventory',
      fact_summaries: [],
      grounding_strength: 'strong',
    },
    analysis: {
      status: 'completed',
      hypotheses: [],
      code_findings: [],
      recommendations: [],
      proposed_fixes: [],
      fix_status: 'unavailable',
      ...analysis,
    },
  }
}

test('whylineFailureSummary joins the top hypothesis and the top fix strategy', () => {
  const issue = issueWithAnalysis({
    hypotheses: [{ statement: 'Changes associated with decrement_inventory may have contributed to the incident.' }],
    proposed_fixes: [
      {
        finding_id: 'f1',
        file_path: 'app/checkout.py',
        function_name: 'decrement_inventory',
        line_start: 13,
        line_end: 13,
        original_hunk: 'STOCK[item_id - 1] -= qty',
        corrected_hunk: 'STOCK[item_id] -= qty',
        failure_mechanism: 'Off-by-one index.',
        fix_strategy: 'Normalize the index used for the final stock lookup.',
        explanation: 'Removes the KeyError.',
      },
    ],
  })
  expect(whylineFailureSummary(issue)).toBe(
    'Changes associated with decrement_inventory may have contributed to the incident. Normalize the index used for the final stock lookup.',
  )
})

test('whylineFailureSummary falls back to just the hypothesis when there is no fix', () => {
  const issue = issueWithAnalysis({ hypotheses: [{ statement: 'Changes associated with X may have contributed.' }] })
  expect(whylineFailureSummary(issue)).toBe('Changes associated with X may have contributed.')
})

test('whylineFailureSummary returns null when neither a hypothesis nor a fix exists', () => {
  expect(whylineFailureSummary(issueWithAnalysis({}))).toBeNull()
})

function finding(overrides: Partial<GroundedCodeFinding>): GroundedCodeFinding {
  return {
    category: 'changed_code_near_failure',
    file_path: 'app/checkout.py',
    line_number: 13,
    function_name: 'decrement_inventory',
    statement: 'The evidence identifies changed code near the observed failure.',
    ...overrides,
  }
}

test('groupCodeFindings collapses findings sharing file, function, line, and category', () => {
  const groups = groupCodeFindings([
    finding({ statement: 'First supporting statement.' }),
    finding({ statement: 'Second supporting statement.' }),
  ])
  expect(groups).toHaveLength(1)
  expect(groups[0].supportingCount).toBe(2)
  expect(groups[0].primary.statement).toBe('First supporting statement.')
  expect(groups[0].duplicates).toEqual([finding({ statement: 'Second supporting statement.' })])
})

test('groupCodeFindings keeps findings in different files or lines as separate groups', () => {
  const groups = groupCodeFindings([
    finding({ file_path: 'app/checkout.py', line_number: 13 }),
    finding({ file_path: 'app/inventory.py', line_number: 20 }),
  ])
  expect(groups).toHaveLength(2)
  expect(groups.every((group) => group.supportingCount === 1)).toBe(true)
})
