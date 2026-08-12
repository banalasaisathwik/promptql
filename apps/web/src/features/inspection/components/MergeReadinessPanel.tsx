/** Render the backend-owned policy decision and its supporting evidence. */

import type {
  PendingAction,
  PolicyFinding,
  PullRequestMergeReadiness,
} from '../types'


interface MergeReadinessPanelProps {
  analysis: PullRequestMergeReadiness | null
  loading: boolean
}


function FindingList({
  title,
  findings,
}: {
  title: string
  findings: PolicyFinding[]
}) {
  if (findings.length === 0) {
    return null
  }

  return (
    <section className="result-section">
      <h3>{title}</h3>
      <ul className="result-list">
        {findings.map((finding, index) => (
          <li key={`${finding.reason_code}-${index}`}>
            <code>{finding.reason_code}</code>
            <p>{finding.message}</p>
            {finding.evidence_reference_ids.length > 0 && (
              <small>
                Evidence: {finding.evidence_reference_ids.join(', ')}
              </small>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}


function ActionList({ actions }: { actions: PendingAction[] }) {
  if (actions.length === 0) {
    return null
  }

  return (
    <section className="result-section">
      <h3>Pending actions</h3>
      <ul className="result-list">
        {actions.map((action, index) => (
          <li key={`${action.action_code}-${index}`}>
            <code>{action.action_code}</code>
            <p>{action.message}</p>
            <small>Reason: {action.reason_code}</small>
          </li>
        ))}
      </ul>
    </section>
  )
}


function RuntimeDetails({ analysis }: { analysis: PullRequestMergeReadiness }) {
  return (
    <section className="result-section" aria-labelledby="runtime-heading">
      <h3 id="runtime-heading">Runtime execution</h3>
      <dl className="evidence-reference-list">
        <div><dt>Run ID</dt><dd><code>{analysis.run_id}</code></dd></div>
        <div><dt>Run status</dt><dd>{analysis.status}</dd></div>
        <div>
          <dt>Sources</dt>
          <dd>
            GitHub: {analysis.sources?.github ?? 'unknown'}; Jira:{' '}
            {analysis.sources?.jira ?? 'unknown'}; explanation:{' '}
            {analysis.sources?.explanation ?? 'unknown'}
          </dd>
        </div>
      </dl>
      <h4>Ordered steps</h4>
      <ol className="result-list">
        {analysis.steps.map((step) => (
          <li key={step.step_id}>
            <code>{step.name}</code> — {step.status}
            {step.duration_ms !== null && <small>{step.duration_ms} ms</small>}
          </li>
        ))}
      </ol>
    </section>
  )
}


function FailedRuntime({ analysis }: { analysis: PullRequestMergeReadiness }) {
  if (analysis.status !== 'failed') {
    return null
  }

  return (
    <div className="inspection-result">
      <section className="decision-card decision-card--blocked">
        <p className="step-label">Runtime failed</p>
        <h3>Merge readiness was not decided</h3>
        <p>{analysis.error.message}</p>
        <code>{analysis.error.code}</code>
      </section>
      <RuntimeDetails analysis={analysis} />
    </div>
  )
}


function AnalysisResult({ analysis }: { analysis: PullRequestMergeReadiness }) {
  if (analysis.status === 'failed') {
    return <FailedRuntime analysis={analysis} />
  }

  const policyResult = analysis.result

  return (
    <div className="inspection-result">
      {/* The decision comes directly from result. No list length or raw
          connector field is used to calculate or replace this value. */}
      <section
        className={`decision-card decision-card--${policyResult.decision}`}
        aria-labelledby="decision-heading"
      >
        <p className="step-label">Overall decision</p>
        <h3 id="decision-heading">{policyResult.decision}</h3>
        <p>{policyResult.summary}</p>
        <code>{policyResult.reason_code}</code>
      </section>

      <RuntimeDetails analysis={analysis} />

      {analysis.explanation ? (
        <section className="result-section explanation-card">
          <p className="step-label">Validated LLM explanation</p>
          <h3>Why this decision was returned</h3>
          <p>{analysis.explanation.summary}</p>
          <h4>Reasons</h4>
          <ul className="result-list">
            {analysis.explanation.reasons.map((reason, index) => (
              <li key={`explanation-reason-${index}`}>{reason}</li>
            ))}
          </ul>
          {analysis.explanation.recommended_actions.length > 0 && (
            <>
              <h4>Recommended actions</h4>
              <ul className="result-list">
                {analysis.explanation.recommended_actions.map(
                  (action, index) => (
                    <li key={`explanation-action-${index}`}>{action}</li>
                  ),
                )}
              </ul>
            </>
          )}
        </section>
      ) : (
        <section className="result-section explanation-card">
          <p className="step-label">Explanation unavailable</p>
          <h3>The policy result is still authoritative</h3>
          <p>{analysis.explanation_error?.message}</p>
          <code>{analysis.explanation_error?.code}</code>
        </section>
      )}

      <FindingList title="Blockers" findings={policyResult.blockers} />
      <ActionList actions={policyResult.pending_actions} />
      <FindingList
        title="Missing information"
        findings={policyResult.missing_information}
      />

      <section className="result-section">
        <h3>Evidence references</h3>
        <dl className="evidence-reference-list">
          {policyResult.evidence_references.map((reference) => (
            <div key={reference.reference_id}>
              <dt>{reference.reference_id}</dt>
              <dd>
                {reference.source}.{reference.field} ={' '}
                {JSON.stringify(reference.value)}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <details className="raw-response">
        <summary>View raw connector facts</summary>
        <pre>
          {JSON.stringify(
            {
              request: analysis.request,
              github: analysis.github,
              jira: analysis.jira,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </div>
  )
}


export function MergeReadinessPanel({
  analysis,
  loading,
}: MergeReadinessPanelProps) {
  return (
    <aside className="preview-card" aria-live="polite" aria-busy={loading}>
      <div className="preview-heading">
        <div>
          <p className="step-label">Backend policy</p>
          <h2>Merge-readiness result</h2>
        </div>
      </div>

      {loading ? (
        <div className="empty-state">
          <div className="spinner" aria-hidden="true" />
          <h3>Analysing merge readiness</h3>
        </div>
      ) : analysis ? (
        <AnalysisResult analysis={analysis} />
      ) : (
        <div className="empty-state">
          <div className="empty-symbol" aria-hidden="true">{'{ }'}</div>
          <h3>Your decision will appear here</h3>
          <p>Select a fixture and ask the backend to evaluate it.</p>
        </div>
      )}
    </aside>
  )
}
