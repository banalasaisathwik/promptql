import { describe, expect, test } from 'bun:test'
import { LiveEventStreamController } from './liveEventStream'
import type { EventSourceLike } from './liveEventStream'
import type { LiveRunEvent } from './types'


class FakeEventSource implements EventSourceLike {
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  closed = false

  constructor(public readonly url: string) {}

  emitOpen(): void {
    this.onopen?.(new Event('open'))
  }

  emitError(): void {
    this.onerror?.(new Event('error'))
  }

  emitMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent)
  }

  close(): void {
    this.closed = true
  }
}


function validEvent(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    event: 'investigation.tool.call_completed',
    level: 'info',
    timestamp: '2026-08-02T10:00:00Z',
    run_id: '49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
    tool_id: 'get_incident',
    tool_outcome: 'observed',
    ...overrides,
  }
}


describe('LiveEventStreamController', () => {
  test('connects to the run-scoped SSE URL', () => {
    let created: FakeEventSource | null = null
    const controller = new LiveEventStreamController({
      runId: '49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
      onEvent: () => undefined,
      onStatusChange: () => undefined,
      createEventSource: (url) => {
        created = new FakeEventSource(url)
        return created
      },
    })

    controller.start()

    expect(created?.url).toBe('/v1/runs/49a8a46d-5c69-4e5d-a928-6a149b84d6e7/events')
  })

  test('reports connecting, then open, then closed on stop', () => {
    const statuses: string[] = []
    let fake: FakeEventSource | null = null
    const controller = new LiveEventStreamController({
      runId: 'run-1',
      onEvent: () => undefined,
      onStatusChange: (status) => statuses.push(status),
      createEventSource: (url) => {
        fake = new FakeEventSource(url)
        return fake
      },
    })

    controller.start()
    fake?.emitOpen()
    controller.stop()

    expect(statuses).toEqual(['connecting', 'open', 'closed'])
    expect(fake?.closed).toBe(true)
  })

  test('an error reports connecting rather than closing the stream', () => {
    const statuses: string[] = []
    let fake: FakeEventSource | null = null
    const controller = new LiveEventStreamController({
      runId: 'run-1',
      onEvent: () => undefined,
      onStatusChange: (status) => statuses.push(status),
      createEventSource: (url) => {
        fake = new FakeEventSource(url)
        return fake
      },
    })

    controller.start()
    fake?.emitOpen()
    fake?.emitError()

    expect(statuses).toEqual(['connecting', 'open', 'connecting'])
    expect(fake?.closed).toBe(false)
  })

  test('parses a valid message into a typed event with envelope and fields split', () => {
    const received: LiveRunEvent[] = []
    let fake: FakeEventSource | null = null
    const controller = new LiveEventStreamController({
      runId: 'run-1',
      onEvent: (event) => received.push(event),
      onStatusChange: () => undefined,
      createEventSource: (url) => {
        fake = new FakeEventSource(url)
        return fake
      },
    })

    controller.start()
    fake?.emitMessage(validEvent())

    expect(received).toEqual([
      {
        event: 'investigation.tool.call_completed',
        level: 'info',
        timestamp: '2026-08-02T10:00:00Z',
        run_id: '49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
        trace_id: undefined,
        span_id: undefined,
        fields: { tool_id: 'get_incident', tool_outcome: 'observed' },
      },
    ])
  })

  test('drops a malformed message without calling onEvent', () => {
    const received: LiveRunEvent[] = []
    let fake: FakeEventSource | null = null
    const controller = new LiveEventStreamController({
      runId: 'run-1',
      onEvent: (event) => received.push(event),
      onStatusChange: () => undefined,
      createEventSource: (url) => {
        fake = new FakeEventSource(url)
        return fake
      },
    })

    controller.start()
    fake?.emitMessage({ level: 'info' })

    expect(received).toEqual([])
  })
})
