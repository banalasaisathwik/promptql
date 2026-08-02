import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import type {
  MergeReadinessDecision,
  PullRequestMergeReadiness,
} from '../types'
import { MergeReadinessPanel } from './MergeReadinessPanel'


function analysisWithDecision(
  decision: MergeReadinessDecision,
): PullRequestMergeReadiness {
  return {
    request: {
      repository_owner: 'acme',
      repository_name: 'analytics',
      pr_number: 1,
    },
    github: null,
    jira: null,
    policy_result: {
      decision,
      summary: `Backend returned ${decision}.`,
      reason_code: decision === 'unknown' ? 'evidence_unavailable' : decision,
      blockers: [],
      pending_actions: [],
      missing_information: [],
      evidence_references: [],
    },
  }
}


describe('MergeReadinessPanel', () => {
  test('renders the backend ready decision prominently', () => {
    const markup = renderToStaticMarkup(
      <MergeReadinessPanel
        analysis={analysisWithDecision('ready')}
        loading={false}
      />,
    )

    expect(markup).toContain('decision-card--ready')
    expect(markup).toContain('id="decision-heading">ready</h3>')
    expect(markup).toContain('Backend returned ready.')
  })

  test('renders every blocker and every pending action', () => {
    const analysis = analysisWithDecision('blocked')
    analysis.policy_result.reason_code = 'ci_check_failed'
    analysis.policy_result.blockers = [
      {
        reason_code: 'ci_check_failed',
        message: 'Unit tests failed.',
        evidence_reference_ids: ['github.required_checks[0].status'],
      },
      {
        reason_code: 'approval_missing',
        message: 'Approval is missing.',
        evidence_reference_ids: ['github.approvals.count'],
      },
    ]
    analysis.policy_result.pending_actions = [
      {
        action_code: 'fix_ci_check',
        reason_code: 'ci_check_failed',
        message: 'Fix unit tests.',
      },
      {
        action_code: 'get_required_approval',
        reason_code: 'approval_missing',
        message: 'Obtain an approval.',
      },
    ]

    const markup = renderToStaticMarkup(
      <MergeReadinessPanel analysis={analysis} loading={false} />,
    )

    expect(markup).toContain('Unit tests failed.')
    expect(markup).toContain('Approval is missing.')
    expect(markup).toContain('Fix unit tests.')
    expect(markup).toContain('Obtain an approval.')
  })

  test('renders missing information for an unknown result', () => {
    const analysis = analysisWithDecision('unknown')
    analysis.policy_result.missing_information = [
      {
        reason_code: 'evidence_unavailable',
        message: 'Jira evidence is unavailable.',
        evidence_reference_ids: [],
      },
    ]

    const markup = renderToStaticMarkup(
      <MergeReadinessPanel analysis={analysis} loading={false} />,
    )

    expect(markup).toContain('decision-card--unknown')
    expect(markup).toContain('Missing information')
    expect(markup).toContain('Jira evidence is unavailable.')
  })

  test('does not derive or override the returned decision from blocker counts', () => {
    const analysis = analysisWithDecision('ready')
    analysis.policy_result.blockers = [
      {
        reason_code: 'ci_check_failed',
        message: 'Contradictory test blocker.',
        evidence_reference_ids: [],
      },
    ]

    const markup = renderToStaticMarkup(
      <MergeReadinessPanel analysis={analysis} loading={false} />,
    )

    expect(markup).toContain('decision-card--ready')
    expect(markup).toContain('id="decision-heading">ready</h3>')
    expect(markup).toContain('Contradictory test blocker.')
    expect(markup).not.toContain('decision-card--blocked')
  })
})
