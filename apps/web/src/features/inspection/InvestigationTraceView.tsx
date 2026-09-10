/**
 * Live investigation trace. The event stream remains the immediate, additive
 * diagnostic signal; the persisted run snapshot supplies durable planning
 * rounds and the final, backend-grounded fact chain.
 */

import { useRunLiveEvents } from './useRunLiveEvents'
import type { LiveEventConnectionStatus } from './useRunLiveEvents'
import { useRunSnapshot } from './useRunSnapshot'
import { runPathFor } from '../../routing'
import type {
  InvestigationPlanningRound,
  InvestigationRun,
  InvestigationStepSnapshot,
  LiveRunEvent,
  RuntimeRun,
  RuntimeStatus,
} from './types'


const TERMINAL_RESULT_LABELS: Record<'completed' | 'failed' | 'cancelled', string> = {
  completed: 'Investigation complete',
  failed: 'Investigation failed',
  cancelled: 'Investigation cancelled',
}


const STATUS_LABELS: Record<LiveEventConnectionStatus, string> = {
  connecting: 'Connecting…',
  open: 'Streaming',
  closed: 'Closed',
}

const STEP_SYMBOLS: Record<InvestigationStepSnapshot['status'], string> = {
  pending: '○',
  running: '•',
  succeeded: '✓',
  failed: '!',
  blocked: '—',
}


type EventTone = 'tool' | 'plan' | 'fact' | 'hypothesis' | 'error'


function formatEventTime(timestamp: string): string {
  const parsed = new Date(timestamp)
  return Number.isNaN(parsed.getTime()) ? timestamp : parsed.toLocaleTimeString()
}


function eventTone(event: LiveRunEvent): EventTone {
  const name = event.event.toLowerCase()
  if (name.includes('error') || event.level === 'error') return 'error'
  // A hypothesis's own validation-rejected event stays in the hypothesis
  // (amber) lane rather than the generic error (red) one below: rejection
  // by the deterministic validator is expected, evaluated behavior, not a
  // runtime failure.
  if (name.includes('hypothesis')) return 'hypothesis'
  if (name.includes('reject')) return 'error'
  if (name.includes('tool')) return 'tool'
  if (name.includes('fact')) return 'fact'
  return 'plan'
}


function eventDetail(event: LiveRunEvent): string {
  const fields = Object.entries(event.fields)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' · ')
  return fields ? `${event.event} · ${fields}` : event.event
}


function isTerminal(status: RuntimeStatus | undefined): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled'
}


function isInvestigationRun(value: RuntimeRun | null): value is InvestigationRun {
  return value !== null && value.workflow_name === 'investigation' && 'state' in value
}


export function TraceRoundSidebar({
  rounds,
}: {
  rounds: InvestigationPlanningRound[]
}) {
  return (
    <aside className="trace-rounds" aria-label="Planning rounds">
      {rounds.length === 0 ? (
        <p className="trace-panel-empty">No planned rounds recorded yet.</p>
      ) : rounds.map((round) => (
        <section className="trace-round" key={round.plan_id}>
          <p className={`trace-round-title trace-round-title--${round.completed ? 'complete' : 'planning'}`}>
            <span aria-hidden="true" />
            Round {round.round_number} · {round.completed ? 'complete' : 'planning'}
          </p>
          <ol className="trace-round-steps">
            {round.steps.map((step) => (
              <li className={`trace-round-step trace-round-step--${step.status}`} key={step.step_id}>
                <span aria-hidden="true">{STEP_SYMBOLS[step.status]}</span>
                {step.tool_id}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </aside>
  )
}


function TraceEventItem({ event }: { event: LiveRunEvent }) {
  const tone = eventTone(event)
  return (
    <li className="trace-log-line" data-event={event.event} data-level={event.level}>
      <time className="trace-log-time" dateTime={event.timestamp}>{formatEventTime(event.timestamp)}</time>
      <span className={`trace-log-tag trace-log-tag--${tone}`}>{tone}</span>
      <span className="trace-log-detail">{eventDetail(event)}</span>
    </li>
  )
}


export function TraceEventList({
  events,
  status,
  streaming = false,
}: {
  events: LiveRunEvent[]
  status: LiveEventConnectionStatus
  streaming?: boolean
}) {
  return (
    <section className="trace-log" aria-labelledby="trace-title">
      <div className="trace-log-head">
        <h2 id="trace-title">Live investigation</h2>
        <span className={`trace-live-badge trace-live-badge--${streaming ? 'streaming' : 'settled'}`}>
          {streaming && <span className="trace-pulse" aria-hidden="true" />}
          {streaming ? 'streaming' : STATUS_LABELS[status]}
        </span>
      </div>
      {events.length === 0 ? (
        <p className="trace-panel-empty">No events received yet.</p>
      ) : (
        <ol className="trace-log-lines" aria-live="polite">
          {events.map((event, index) => <TraceEventItem event={event} key={index} />)}
          {streaming && <li className="trace-cursor" aria-label="Waiting for the next event" />}
        </ol>
      )}
    </section>
  )
}


export function FactChainPanel({ chain }: { chain: string[] | null }) {
  return (
    <aside className="trace-chain" aria-label="Connected fact chain">
      <p className="trace-chain-title">Fact chain forming</p>
      {chain && chain.length > 0 ? (
        <ol className="trace-chain-nodes">
          {chain.map((node, index) => (
            <li className="trace-chain-node trace-chain-node--active" key={`${node}-${index}`}>
              {node}
            </li>
          ))}
        </ol>
      ) : (
        <p className="trace-panel-empty">
          No connected fact chain has been produced for this run yet.
        </p>
      )}
    </aside>
  )
}


export function TraceResultBanner({ runId, status }: { runId: string, status: RuntimeStatus | undefined }) {
  if (!isTerminal(status)) {
    return null
  }
  const label = TERMINAL_RESULT_LABELS[status as 'completed' | 'failed' | 'cancelled']
  return (
    <a className={`trace-result-banner trace-result-banner--${status}`} href={runPathFor(runId)}>
      <span>{label}</span>
      <span className="trace-result-banner-cta">View full result →</span>
    </a>
  )
}


function traceFactChain(run: InvestigationRun | null): string[] | null {
  const latestResult = run?.results[run.results.length - 1]
  const hypothesisWithChain = latestResult?.supported_hypotheses.find(
    (hypothesis) => hypothesis.connected_fact_chain?.length,
  )
  return hypothesisWithChain?.connected_fact_chain ?? null
}


export function InvestigationTraceView({ runId }: { runId: string }) {
  const { events, status } = useRunLiveEvents(runId)
  const { snapshot } = useRunSnapshot(runId)
  const investigation = isInvestigationRun(snapshot) ? snapshot : null
  const rounds = investigation?.state?.execution_state.rounds ?? []
  const streaming = status === 'open' && !isTerminal(investigation?.status)

  return (
    <main className="app-shell trace-view">
      <header className="site-header">
        <a className="brand" href="/" aria-label="Whyline home">
          <span className="brand-mark" aria-hidden="true">W</span>
          <span>Whyline</span>
        </a>
        <span className="environment-badge">Live trace</span>
      </header>

      <TraceResultBanner runId={runId} status={investigation?.status} />

      <section className="trace-grid" aria-label={`Live trace for run ${runId}`}>
        <TraceRoundSidebar rounds={rounds} />
        <TraceEventList events={events} status={status} streaming={streaming} />
        <FactChainPanel chain={traceFactChain(investigation)} />
      </section>
    </main>
  )
}
