import { useState } from 'react'
import type { FormEvent } from 'react'
import { startInvestigationFollowUp } from './api'
import { ConnectorApiError } from './apiError'
import type {
  DeveloperRecommendation,
  GroundedInvestigationResult,
  InvestigationEvidence,
  InvestigationFact,
  InvestigationRun,
  InvestigationStepSnapshot,
  InvestigationMissingInformation,
  ValidatedCodeFinding,
} from './types'


const STATUS_LABELS: Record<InvestigationStepSnapshot['status'], string> = {
  pending: 'Pending',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  blocked: 'Blocked',
}


function evidenceSummary(evidence: InvestigationEvidence): string {
  const content = evidence.content
  if (typeof content.path === 'string') return `Changed file: ${content.path}`
  if (typeof content.file_path === 'string') return `Failure location: ${content.file_path}`
  if (typeof content.incident_reference === 'string') return `Incident: ${content.incident_reference}`
  if (typeof content.deployment_reference === 'string') return `Deployment: ${content.deployment_reference}`
  if (typeof content.service === 'string') return `Service: ${content.service}`
  return `${evidence.kind} evidence from ${evidence.source}`
}


function factLabel(fact: InvestigationFact): string {
  const entity = typeof fact.path === 'string'
    ? fact.path
    : typeof fact.file_path === 'string'
      ? fact.file_path
      : typeof fact.deployment_reference === 'string'
        ? fact.deployment_reference
        : fact.fact_id
  return `${fact.fact_type.replaceAll('_', ' ')}: ${entity}`
}


function MissingInformationList({ items }: { items: InvestigationMissingInformation[] }) {
  if (items.length === 0) return <p className="run-empty">No missing information recorded.</p>
  return <ul className="plain-list">{items.map((item) => <li key={item.missing_information_id}>{item.detail ?? item.kind.replaceAll('_', ' ')}</li>)}</ul>
}


function codeFindingLocation(finding: ValidatedCodeFinding): string {
  // The browser formats backend-owned coordinates; it never guesses a nearest
  // line or reconstructs a location from Evidence content.
  const line = finding.line_number === null ? '' : `:${finding.line_number}`
  const functionName = finding.function_name === null ? '' : ` in ${finding.function_name}`
  return `${finding.file_path}${line}${functionName}`
}


function RecommendationList({ items }: { items: DeveloperRecommendation[] }) {
  // Recommendation messages are deterministic backend output, not prose
  // generated or expanded by this presentation component.
  if (items.length === 0) return <p className="run-empty">No developer action is supported by a validated code finding.</p>
  return <ul className="plain-list">{items.map((item) => <li key={item.recommendation_id}><strong>{item.message}</strong><small>{item.code.replaceAll('_', ' ')} · supported by {item.supporting_fact_ids.join(', ')}</small></li>)}</ul>
}


// One entry in the growing thread (ADR-033): the original investigation's
// result is always index 0, and each follow-up appends one more result after
// it. Nothing here is ever replaced or removed once rendered.
function GroundedResultSection({
  result,
  index,
}: {
  result: GroundedInvestigationResult
  index: number
}) {
  const titleId = `grounded-result-title-${index}`
  return (
    <section className="run-result" aria-labelledby={titleId}>
      <p className="eyebrow">{index === 0 ? 'Original investigation result' : `Follow-up result ${index}`}</p>
      <h2 id={titleId}>{result.supported_hypotheses.length ? 'Likely contributing factor' : 'No supported causal hypothesis'}</h2>
      <p>{result.summary}</p>
      {result.supported_hypotheses.map((hypothesis) => <article className="grounded-hypothesis" key={hypothesis.hypothesis_id}><h3>{hypothesis.statement}</h3><p>Supporting Facts: {hypothesis.supporting_fact_ids.join(', ')}</p></article>)}
      {result.code_findings.map((finding) => <article className="grounded-hypothesis" key={finding.finding_id}><h3>{finding.statement}</h3><p>Exact validated location: {codeFindingLocation(finding)}</p></article>)}
      {result.recommendations.length > 0 && <div><h3>Grounded actions</h3><RecommendationList items={result.recommendations} /></div>}
      <p className="terminal-note">Stopped because: {result.termination_reason.replaceAll('_', ' ')}</p>
    </section>
  )
}


function FollowUpForm({
  runId,
  onSubmitted,
}: {
  runId: string
  onSubmitted: () => void
}) {
  const [question, setQuestion] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting || !question.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await startInvestigationFollowUp(runId, question.trim())
      setQuestion('')
      onSubmitted()
    } catch (caught) {
      // The backend already writes a direct, user-facing message for both
      // the 404 (unknown run) and 409 (not completed / follow-up limit
      // reached) cases (ADR-033), so it is shown as-is rather than mapped.
      setError(
        caught instanceof ConnectorApiError
          ? caught.message
          : 'The follow-up question could not be submitted.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="run-card" aria-labelledby="follow-up-title">
      <p className="step-label">Continue this investigation</p>
      <h2 id="follow-up-title">Ask a follow-up</h2>
      <form onSubmit={submit}>
        <label>
          <span>Follow-up question</span>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask another question building on this investigation's evidence…"
            rows={3}
          />
        </label>
        <button className="primary-action" type="submit" disabled={submitting || !question.trim()}>
          {submitting ? 'Submitting follow-up…' : 'Submit follow-up'}
        </button>
        {error && <p className="inline-alert" role="alert">{error}</p>}
      </form>
    </section>
  )
}


export function InvestigationDashboard({
  run,
  onFollowUpSubmitted,
}: {
  run: InvestigationRun
  onFollowUpSubmitted?: () => void
}) {
  const state = run.state
  const results = run.results
  return (
    <>
      <section className="run-header" aria-labelledby="investigation-run-title">
        <div>
          <p className="eyebrow">Live investigation snapshot</p>
          <h1 id="investigation-run-title">{run.request.repository_name}</h1>
          <p className="intro-copy">{run.request.question}</p>
        </div>
        <div className={`run-status run-status--${run.status}`}><span>{run.status}</span></div>
      </section>

      <section className="run-summary-grid">
        <article className="run-card"><p className="step-label">Tool calls</p><h2>{state?.execution_state.used_tool_calls ?? 0} / {state?.execution_state.max_tool_calls ?? '—'}</h2><p>{state?.execution_state.remaining_tool_calls ?? 'Waiting for execution'} remaining</p></article>
        <article className="run-card"><p className="step-label">Planning rounds</p><h2>{state?.execution_state.rounds.length ?? 0}</h2><p>{state?.execution_state.termination_reason?.replaceAll('_', ' ') ?? 'Execution is starting'}</p></article>
      </section>

      {run.error && <section className="run-card run-card--error"><p className="step-label">Runtime error</p><h2>{run.error.code}</h2><p>{run.error.message}</p></section>}

      <section className="run-card" aria-labelledby="investigation-timeline-title">
        <div className="run-section-heading"><div><p className="step-label">Planning and execution</p><h2 id="investigation-timeline-title">Investigation timeline</h2></div></div>
        {!state || state.execution_state.rounds.length === 0 ? <p className="run-empty">The investigation has not recorded a planning round yet.</p> : state.execution_state.rounds.map((round) => (
          <div className="investigation-round" key={round.plan_id}>
            <h3>Round {round.round_number} <small>{round.plan_validation_status}</small></h3>
            <ol className="run-timeline">{round.steps.map((step) => <li className={`run-step run-step--${step.status}`} key={step.step_id}><span className="run-step-symbol" aria-hidden="true">{step.status === 'succeeded' ? '✓' : step.status === 'failed' ? '!' : step.status === 'blocked' ? '—' : '•'}</span><div className="run-step-copy"><strong>{step.tool_id}</strong><span>{STATUS_LABELS[step.status]}</span><small>Attempt(s): {step.attempts}</small>{step.failure_message && <p className="run-step-error">{step.failure_message}</p>}{step.block_reason && <small>Blocked: {step.block_reason.replaceAll('_', ' ')}</small>}</div></li>)}</ol>
          </div>
        ))}
      </section>

      <section className="run-card" aria-labelledby="evidence-title"><div className="run-section-heading"><div><p className="step-label">Evidence</p><h2 id="evidence-title">Normalized observations</h2></div><span>{state?.working_memory.evidence_content.length ?? 0}</span></div>{state?.working_memory.evidence_content.length ? <ul className="plain-list">{state.working_memory.evidence_content.map((item) => <li key={item.evidence_id}><strong>{evidenceSummary(item)}</strong><small>{item.source} · {item.evidence_id}</small></li>)}</ul> : <p className="run-empty">Evidence will appear as tools return normalized observations.</p>}</section>

      <section className="run-card" aria-labelledby="facts-title"><div className="run-section-heading"><div><p className="step-label">Facts</p><h2 id="facts-title">Derived deterministic facts</h2></div><span>{state?.working_memory.facts.length ?? 0}</span></div>{state?.working_memory.facts.length ? <ul className="plain-list">{state.working_memory.facts.map((fact) => <li key={fact.fact_id}><strong>{factLabel(fact)}</strong><small>Derived from {fact.evidence_reference_ids.join(', ')}</small></li>)}</ul> : <p className="run-empty">No Facts have been derived yet.</p>}</section>

      <section className="run-card" aria-labelledby="missing-title"><p className="step-label">Missing information</p><h2 id="missing-title">Known gaps</h2><MissingInformationList items={state?.working_memory.missing_information ?? []} /></section>

      <section className="run-card" aria-labelledby="hypotheses-title"><p className="step-label">Hypotheses</p><h2 id="hypotheses-title">Validated hypotheses</h2>{state?.working_memory.validated_hypotheses.length ? <ul className="plain-list">{state.working_memory.validated_hypotheses.map((hypothesis) => <li key={hypothesis.hypothesis_id}><strong>{hypothesis.subject}</strong><small>{hypothesis.kind.replaceAll('_', ' ')} · supported by {hypothesis.supporting_fact_ids.join(', ')}</small></li>)}</ul> : <p className="run-empty">No validated causal hypothesis is available. Rejected candidate count: {state?.execution_state.rejected_hypothesis_count ?? 0}.</p>}</section>

      <section className="run-card" aria-labelledby="code-findings-title"><p className="step-label">Code diagnosis</p><h2 id="code-findings-title">Validated code findings</h2>{state?.working_memory.validated_code_findings.length ? <ul className="plain-list">{state.working_memory.validated_code_findings.map((finding) => <li key={finding.finding_id}><strong>{codeFindingLocation(finding)}</strong><small>{finding.category.replaceAll('_', ' ')} · supported by {finding.supporting_fact_ids.join(', ')}</small></li>)}</ul> : <p className="run-empty">No code location passed deterministic grounding. Rejected candidate count: {state?.execution_state.rejected_code_finding_count ?? 0}.</p>}</section>

      <section className="run-card" aria-labelledby="recommendations-title"><p className="step-label">Next steps</p><h2 id="recommendations-title">Recommended developer actions</h2><RecommendationList items={state?.working_memory.developer_recommendations ?? []} /></section>

      {results.map((result, index) => <GroundedResultSection result={result} index={index} key={index} />)}

      {run.status === 'completed' && (
        <FollowUpForm runId={run.run_id} onSubmitted={onFollowUpSubmitted ?? (() => {})} />
      )}
    </>
  )
}
