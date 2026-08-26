/**
 * Minimal live trace view: a chronological list of one run's structured
 * events, received over the SSE stream in useRunLiveEvents.ts.
 *
 * This is a new, additive admin/trace view. It does not replace, poll, or
 * read from RunDashboardPage.tsx / useRunSnapshot.ts / runPolling.ts, and
 * carries no historical replay of its own - only events received while this
 * page is open.
 */

import { useRunLiveEvents } from './useRunLiveEvents'
import type { LiveEventConnectionStatus } from './useRunLiveEvents'
import type { LiveRunEvent } from './types'


const STATUS_LABELS: Record<LiveEventConnectionStatus, string> = {
  connecting: 'Connecting…',
  open: 'Live',
  closed: 'Closed',
}


function formatEventTime(timestamp: string): string {
  const parsed = new Date(timestamp)
  return Number.isNaN(parsed.getTime()) ? timestamp : parsed.toLocaleTimeString()
}


function TraceEventItem({ event, index }: { event: LiveRunEvent; index: number }) {
  const fieldEntries = Object.entries(event.fields)

  return (
    <li className="trace-event">
      <span className="trace-event-index" aria-hidden="true">{index + 1}</span>
      <div className="trace-event-copy">
        <strong>{event.event}</strong>
        <span>{formatEventTime(event.timestamp)} · {event.level}</span>
        {fieldEntries.length > 0 && (
          <dl className="trace-event-fields">
            {fieldEntries.map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </li>
  )
}


export function TraceEventList({
  events,
  status,
}: {
  events: LiveRunEvent[]
  status: LiveEventConnectionStatus
}) {
  return (
    <section className="run-card" aria-labelledby="trace-title">
      <div className="run-section-heading">
        <div>
          <p className="step-label">Connection: {STATUS_LABELS[status]}</p>
          <h2 id="trace-title">Live events</h2>
        </div>
        <span>{events.length} received</span>
      </div>
      {events.length === 0 ? (
        <p className="run-empty">No events received yet.</p>
      ) : (
        <ol className="trace-event-list">
          {events.map((event, index) => (
            <TraceEventItem key={index} event={event} index={index} />
          ))}
        </ol>
      )}
    </section>
  )
}


export function InvestigationTraceView({ runId }: { runId: string }) {
  const { events, status } = useRunLiveEvents(runId)

  return (
    <main className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="PromptQL home">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span>PromptQL</span>
        </a>
        <span className="environment-badge">Live trace</span>
      </header>

      <section className="workspace run-workspace">
        <div>
          <p className="eyebrow">Live event stream</p>
          <h1>Trace for run {runId}</h1>
          <p className="intro-copy">
            <a href={`/runs/${encodeURIComponent(runId)}`}>Back to the run dashboard</a>
          </p>
        </div>
        <TraceEventList events={events} status={status} />
      </section>
    </main>
  )
}
