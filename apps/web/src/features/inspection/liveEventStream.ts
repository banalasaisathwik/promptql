/**
 * Framework-free controller wrapping one run's live-event SSE connection.
 *
 * Mirrors runPolling.ts's split from its React hook (useRunSnapshot.ts):
 * this class knows nothing about React, so it is unit-testable with a fake
 * EventSource, while useRunLiveEvents.ts only wires it to component state.
 */

import { parseLiveRunEvent } from './responseValidation'
import type { LiveRunEvent } from './types'


export type LiveEventConnectionStatus = 'connecting' | 'open' | 'closed'

// The subset of the browser EventSource surface this controller uses, so
// tests can supply a fake without a DOM.
export interface EventSourceLike {
  onopen: ((event: Event) => void) | null
  onerror: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  close(): void
}

export type EventSourceFactory = (url: string) => EventSourceLike

const TERMINAL_WORKFLOW_EVENTS = new Set([
  'runtime.workflow.completed',
  'runtime.workflow.failed',
])

interface LiveEventStreamControllerOptions {
  runId: string
  onEvent: (event: LiveRunEvent) => void
  onStatusChange: (status: LiveEventConnectionStatus) => void
  createEventSource?: EventSourceFactory
}


export class LiveEventStreamController {
  private readonly runId: string
  private readonly onEvent: (event: LiveRunEvent) => void
  private readonly onStatusChange: (status: LiveEventConnectionStatus) => void
  private readonly createEventSource: EventSourceFactory
  private source: EventSourceLike | null = null

  constructor(options: LiveEventStreamControllerOptions) {
    this.runId = options.runId
    this.onEvent = options.onEvent
    this.onStatusChange = options.onStatusChange
    this.createEventSource =
      options.createEventSource ?? ((url) => new EventSource(url))
  }

  start(): void {
    // The relative URL works through Vite's development proxy and through a
    // production same-origin router, matching the fetch calls in api.ts.
    const source = this.createEventSource(
      `/v1/runs/${encodeURIComponent(this.runId)}/events`,
    )
    this.source = source
    this.onStatusChange('connecting')

    source.onopen = () => {
      this.onStatusChange('open')
    }
    source.onerror = () => {
      // EventSource retries the connection on its own; an error does not
      // mean the run ended, so this reflects "not open right now" rather
      // than closing the stream itself.
      this.onStatusChange('connecting')
    }
    source.onmessage = (message) => {
      let parsed: LiveRunEvent
      try {
        parsed = parseLiveRunEvent(JSON.parse(message.data))
      } catch {
        // Malformed or unrecognized payloads are dropped: this is a
        // diagnostic tap, not a contract the UI must enforce strictly.
        return
      }
      this.onEvent(parsed)
      if (TERMINAL_WORKFLOW_EVENTS.has(parsed.event)) {
        this.stop()
      }
    }
  }

  stop(): void {
    this.source?.close()
    this.source = null
    this.onStatusChange('closed')
  }
}
