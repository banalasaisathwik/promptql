import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import type {
  CompletedMergeReadinessRun,
  MergeReadinessDecision,
  PullRequestMergeReadiness,
} from '../types'
import { MergeReadinessPanel } from './MergeReadinessPanel'


function analysisWithDecision(
  decision: MergeReadinessDecision,
): CompletedMergeReadinessRun {
  return {
    run_id: '49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
    workflow_name: 'merge_readiness',
    workflow_version: '1',
    sources: { github: 'live', jira: 'fake', explanation: 'gemini' },
    status: 'completed',
    started_at: '2026-08-02T10:00:00Z',
    completed_at: '2026-08-02T10:00:01Z',
    steps: [],
    error: null,
    request: {
      repository_owner: 'acme',
      repository_name: 'analytics',
      pr_number: 1,
    },
    github: null,
    jira: null,
    result: {
      decision,
      summary: `Backend returned ${decision}.`,
      reason_code: decision === 'unknown' ? 'evidence_unavailable' : decision,
      blockers: [],
      pending_actions: [],
      missing_information: [],
      evidence_references: [],
    },
    explanation: {
      decision,
      summary: `Validated explanation for ${decision}.`,
      reasons: [`Explanation reason for ${decision}.`],
      recommended_actions: [],
    },
    explanation_error: null,
  }
}


describe('MergeReadinessPanel', () => {
  test('renders run metadata, ordered steps, and source provenance', () => {
    const analysis = analysisWithDecision('ready')
    analysis.steps = [
      {
        step_id: 'c3bdb98c-1389-4eb8-a8bb-b004b323dd64',
        name: 'fetch_github_facts',
        status: 'completed',
        started_at: '2026-08-02T10:00:00Z',
        completed_at: '2026-08-02T10:00:00.010Z',
        duration_ms: 10,
        attempt: 1,
        error: null,
      },
    ]

    const markup = renderToStaticMarkup(
      <MergeReadinessPanel analysis={analysis} loading={false} />,
    )

    expect(markup).toContain(analysis.run_id)
    expect(markup).toContain('Run status')
    expect(markup).toContain('GitHub: live; Jira: fake; explanation: gemini')
    expect(markup).toContain('fetch_github_facts')
    expect(markup).toContain('10 ms')
  })

  test('renders a typed failed run without inventing an unknown decision', () => {
    const completed = analysisWithDecision('ready')
    const failed: PullRequestMergeReadiness = {
      ...completed,
      status: 'failed',
      result: null,
      error: {
        code: 'connector_execution_failed',
        message: 'The GitHub connector step failed unexpectedly.',
      },
      explanation: null,
      explanation_error: null,
    }

    const markup = renderToStaticMarkup(
      <MergeReadinessPanel analysis={failed} loading={false} />,
    )

    expect(markup).toContain('Runtime failed')
    expect(markup).toContain(failed.run_id)
    expect(markup).toContain('connector_execution_failed')
    expect(markup).not.toContain('decision-card--unknown')
  })

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
    expect(markup).toContain('Validated LLM explanation')
    expect(markup).not.toContain('Validated fake LLM explanation')
    expect(markup).toContain('Validated explanation for ready.')
  })

  test('renders every validated explanation reason and action', () => {
    const analysis = analysisWithDecision('blocked')
    analysis.explanation = {
      decision: 'blocked',
      summary: 'The deterministic policy found verified merge blockers.',
      reasons: ['A required CI check failed.', 'A required approval is missing.'],
      recommended_actions: [
        'Fix the failed required CI check.',
        'Obtain the missing required approval.',
      ],
    }

    const markup = renderToStaticMarkup(
      <MergeReadinessPanel analysis={analysis} loading={false} />,
    )

    expect(markup).toContain('A required CI check failed.')
    expect(markup).toContain('A required approval is missing.')
    expect(markup).toContain('Fix the failed required CI check.')
    expect(markup).toContain('Obtain the missing required approval.')
  })

  test('shows explanation failure without changing the policy decision', () => {
    const analysis = analysisWithDecision('ready')
    analysis.explanation = null
    analysis.explanation_error = {
      code: 'validation_failed',
      message: 'The generated explanation did not pass validation.',
    }

    const markup = renderToStaticMarkup(
      <MergeReadinessPanel analysis={analysis} loading={false} />,
    )

    expect(markup).toContain('decision-card--ready')
    expect(markup).toContain('id="decision-heading">ready</h3>')
    expect(markup).toContain('Explanation unavailable')
    expect(markup).toContain('validation_failed')
  })

  test('renders every blocker and every pending action', () => {
    const analysis = analysisWithDecision('blocked')
    analysis.result.reason_code = 'ci_check_failed'
    analysis.result.blockers = [
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
    analysis.result.pending_actions = [
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
    analysis.result.missing_information = [
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
    analysis.result.blockers = [
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
