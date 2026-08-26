/**
 * Live tap on one run's structured runtime events via Server-Sent Events.
 *
 * This is additive to, not a replacement for, the existing polling dashboard
 * (RunPollingController / useRunSnapshot): it has no knowledge of run status
 * or termination, and carries no historical replay (a browser that connects
 * late sees nothing that happened before it connected).
 */

import { useEffect, useState } from 'react'
import { LiveEventStreamController } from './liveEventStream'
import type { LiveEventConnectionStatus } from './liveEventStream'
import type { LiveRunEvent } from './types'


interface UseRunLiveEventsResult {
  events: LiveRunEvent[]
  status: LiveEventConnectionStatus
}

// A long-running investigation could otherwise grow this array without
// bound; the trace view only ever needs to show the most recent activity.
const MAX_BUFFERED_EVENTS = 500


export function useRunLiveEvents(runId: string): UseRunLiveEventsResult {
  const [events, setEvents] = useState<LiveRunEvent[]>([])
  const [status, setStatus] = useState<LiveEventConnectionStatus>('connecting')

  useEffect(() => {
    setEvents([])
    setStatus('connecting')

    const controller = new LiveEventStreamController({
      runId,
      onEvent: (event) => {
        setEvents((previous) => {
          const next = [...previous, event]
          return next.length > MAX_BUFFERED_EVENTS
            ? next.slice(next.length - MAX_BUFFERED_EVENTS)
            : next
        })
      },
      onStatusChange: setStatus,
    })
    controller.start()

    return () => controller.stop()
  }, [runId])

  return { events, status }
}

export type { LiveEventConnectionStatus }
