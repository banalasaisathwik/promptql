import { MergeReadinessPanel } from './components/MergeReadinessPanel'
import { useRunSnapshot } from './useRunSnapshot'
import { InvestigationDashboard } from './InvestigationDashboard'
import type {
  InvestigationRun,
  PullRequestMergeReadiness,
  RuntimeRun,
  RuntimeStatus,
  RuntimeStep,
  WorkflowStepName,
} from './types'


const STEP_LABELS: Record<WorkflowStepName, string> = {
  fetch_github_facts: 'Fetch GitHub facts',
  fetch_jira_facts: 'Fetch Jira facts',
  evaluate_merge_readiness: 'Evaluate merge readiness',
}

const STATUS_LABELS: Record<RuntimeStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

const STATUS_SYMBOLS: Record<RuntimeStatus, string> = {
  pending: '○',
  running: '●',
  completed: '✓',
  failed: '✕',
  cancelled: '–',
}


function formatTimestamp(timestamp: string | null): string {
  if (timestamp === null) {
    return 'Not recorded yet'
  }
  return new Date(timestamp).toLocaleString()
}


function formatDuration(durationMilliseconds: number | null): string {
  if (durationMilliseconds === null) {
    return 'In progress'
  }
  return `${durationMilliseconds} ms`
}


function formatElapsed(run: PullRequestMergeReadiness): string {
  if (run.started_at === null) {
    return 'Waiting to start'
  }
  const end = run.completed_at === null ? Date.now() : Date.parse(run.completed_at)
  const elapsedMilliseconds = Math.max(0, end - Date.parse(run.started_at))
  return `${(elapsedMilliseconds / 1_000).toFixed(1)}s`
}


function currentActivity(run: PullRequestMergeReadiness): string {
  const runningStep = run.steps.find((step) => step.status === 'running')
  if (runningStep) {
    return STEP_LABELS[runningStep.name]
  }
  if (run.status === 'pending') {
    return 'Waiting to start'
  }
  return `Workflow ${STATUS_LABELS[run.status].toLowerCase()}`
}


function StepTimelineItem({ step }: { step: RuntimeStep }) {
  return (
    <li className={`run-step run-step--${step.status}`}>
      <span className="run-step-symbol" aria-hidden="true">
        {STATUS_SYMBOLS[step.status]}
      </span>
      <div className="run-step-copy">
        <strong>{STEP_LABELS[step.name]}</strong>
        <span>{STATUS_LABELS[step.status]}</span>
        <small>
          Started: {formatTimestamp(step.started_at)} · Completed:{' '}
          {formatTimestamp(step.completed_at)} · Attempt {step.attempt}
        </small>
        {step.error && (
          <p className="run-step-error">
            {step.error.code}: {step.error.message}
          </p>
        )}
      </div>
      <span className="run-step-duration">{formatDuration(step.duration_ms)}</span>
    </li>
  )
}


export function RunDashboard({ run }: { run: PullRequestMergeReadiness }) {
  return (
    <>
      <section className="run-header" aria-labelledby="run-title">
        <div>
          <p className="eyebrow">Live workflow snapshot</p>
          <h1 id="run-title">Run {run.run_id}</h1>
          <p className="intro-copy">
            {run.workflow_name.replaceAll('_', ' ')} v{run.workflow_version}
          </p>
        </div>
        <div className={`run-status run-status--${run.status}`}>
          <span>{STATUS_LABELS[run.status]}</span>
          <small>{formatElapsed(run)}</small>
        </div>
      </section>

      <section className="run-summary-grid">
        <article className="run-card">
          <p className="step-label">Current activity</p>
          <h2>{currentActivity(run)}</h2>
          <p>{run.status === 'running' ? 'Polling persisted runtime state.' : 'Derived from the current run snapshot.'}</p>
        </article>
        <article className="run-card">
          <p className="step-label">Run metadata</p>
          <dl className="run-metadata">
            <div><dt>Started</dt><dd>{formatTimestamp(run.started_at)}</dd></div>
            <div><dt>Completed</dt><dd>{formatTimestamp(run.completed_at)}</dd></div>
            <div><dt>GitHub</dt><dd>{run.sources?.github ?? 'unknown'}</dd></div>
            <div><dt>Jira</dt><dd>{run.sources?.jira ?? 'unknown'}</dd></div>
            <div><dt>Explanation</dt><dd>{run.sources?.explanation ?? 'unknown'}</dd></div>
          </dl>
        </article>
      </section>

      <section className="run-card" aria-labelledby="timeline-title">
        <div className="run-section-heading">
          <div>
            <p className="step-label">Execution</p>
            <h2 id="timeline-title">Ordered runtime steps</h2>
          </div>
          <span>{run.steps.length} recorded</span>
        </div>
        {run.steps.length === 0 ? (
          <p className="run-empty">The pending snapshot has no started steps yet.</p>
        ) : (
          <ol className="run-timeline">
            {run.steps.map((step) => <StepTimelineItem key={step.step_id} step={step} />)}
          </ol>
        )}
      </section>

      {run.error && (
        <section className="run-card run-card--error" aria-labelledby="run-error-title">
          <p className="step-label">Runtime error</p>
          <h2 id="run-error-title">{run.error.code}</h2>
          <p>{run.error.message}</p>
        </section>
      )}

      {run.status === 'completed' && (
        <section className="run-result" aria-label="Final merge-readiness result">
          <MergeReadinessPanel analysis={run} loading={false} />
        </section>
      )}

      <details className="raw-response run-raw">
        <summary>Raw Run</summary>
        <pre>{JSON.stringify(run, null, 2)}</pre>
      </details>
    </>
  )
}


export function RuntimeDashboard({ run }: { run: RuntimeRun }) {
  if (run.workflow_name === 'investigation') {
    return <InvestigationDashboard run={run as InvestigationRun} />
  }
  return <RunDashboard run={run as PullRequestMergeReadiness} />
}


export function RunDashboardPage({ runId }: { runId: string }) {
  const { snapshot, loading, refreshError } = useRunSnapshot(runId)

  return (
    <main className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="PromptQL home">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span>PromptQL</span>
        </a>
        <span className="environment-badge">Runtime dashboard</span>
      </header>

      <section className="workspace run-workspace" aria-busy={loading}>
        {refreshError && (
          <p className="inline-alert" role="status">
            Dashboard refresh failed: {refreshError}. The workflow status above is unchanged.
          </p>
        )}
        {loading && snapshot === null ? (
          <div className="empty-state">
            <div className="spinner" aria-hidden="true" />
            <h3>Loading persisted run</h3>
            <p>The dashboard will render only after the API response is validated.</p>
          </div>
        ) : snapshot ? (
          <RuntimeDashboard run={snapshot} />
        ) : (
          <div className="empty-state">
            <div className="empty-symbol" aria-hidden="true">!</div>
            <h3>Run could not be loaded</h3>
            <p>Check the run ID and backend connection, then the dashboard will retry.</p>
          </div>
        )}
      </section>
    </main>
  )
}
