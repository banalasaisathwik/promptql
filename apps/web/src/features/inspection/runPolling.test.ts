import { describe, expect, test } from 'bun:test'
import { RunPollingController } from './runPolling'
import type { PullRequestMergeReadiness } from './types'


const RUNNING_SNAPSHOT: PullRequestMergeReadiness = {
  run_id: '49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
  workflow_name: 'merge_readiness',
  workflow_version: '1',
  sources: { github: 'fake', jira: 'fake', explanation: 'fake' },
  status: 'running',
  started_at: '2026-08-02T10:00:00Z',
  completed_at: null,
  steps: [],
  error: null,
  result: null,
  explanation: null,
  explanation_error: null,
  request: { repository_owner: 'acme', repository_name: 'analytics', pr_number: 1 },
  github: null,
  jira: null,
}

const COMPLETED_SNAPSHOT: PullRequestMergeReadiness = {
  ...RUNNING_SNAPSHOT,
  status: 'completed',
  completed_at: '2026-08-02T10:00:01Z',
  result: {
    decision: 'ready',
    summary: 'The backend decided readiness.',
    reason_code: 'ready',
    blockers: [],
    pending_actions: [],
    missing_information: [],
    evidence_references: [],
  },
  explanation: {
    decision: 'ready',
    summary: 'Validated explanation.',
    reasons: [],
    recommended_actions: [],
  },
}

const FAILED_SNAPSHOT: PullRequestMergeReadiness = {
  ...RUNNING_SNAPSHOT,
  status: 'failed',
  completed_at: '2026-08-02T10:00:01Z',
  error: {
    code: 'connector_execution_failed',
    message: 'The GitHub connector step failed unexpectedly.',
  },
}


function wait(milliseconds = 0): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}


describe('RunPollingController', () => {
  test('serializes refreshes and stops after a terminal snapshot', async () => {
    let calls = 0
    const snapshots: PullRequestMergeReadiness[] = []
    const controller = new RunPollingController({
      intervalMilliseconds: 1,
      loadSnapshot: async () => {
        calls += 1
        return COMPLETED_SNAPSHOT
      },
      onSnapshot: (snapshot) => snapshots.push(snapshot),
      onRefreshError: () => undefined,
    })

    controller.start()
    await wait(5)
    await wait(5)

    expect(calls).toBe(1)
    expect(snapshots).toEqual([COMPLETED_SNAPSHOT])
    controller.stop()
  })

  test('does not overlap a slow refresh and retries a non-terminal snapshot', async () => {
    let calls = 0
    let finishFirstRequest: ((snapshot: PullRequestMergeReadiness) => void) | null = null
    const controller = new RunPollingController({
      intervalMilliseconds: 1,
      loadSnapshot: async () => {
        calls += 1
        if (calls === 1) {
          return new Promise((resolve) => { finishFirstRequest = resolve })
        }
        return COMPLETED_SNAPSHOT
      },
      onSnapshot: () => undefined,
      onRefreshError: () => undefined,
    })

    controller.start()
    await wait(5)
    expect(calls).toBe(1)
    await wait(5)
    expect(calls).toBe(1)

    finishFirstRequest?.(RUNNING_SNAPSHOT)
    await wait(10)
    expect(calls).toBe(2)
    controller.stop()
  })

  test('stops after a failed workflow snapshot', async () => {
    let calls = 0
    const controller = new RunPollingController({
      intervalMilliseconds: 1,
      loadSnapshot: async () => {
        calls += 1
        return FAILED_SNAPSHOT
      },
      onSnapshot: () => undefined,
      onRefreshError: () => undefined,
    })

    controller.start()
    await wait(15)

    expect(calls).toBe(1)
    controller.stop()
  })

  test('keeps a refresh failure separate and aborts an in-flight request on stop', async () => {
    const errors: string[] = []
    let capturedSignal: AbortSignal | null = null
    let finishRequest: (() => void) | null = null
    const controller = new RunPollingController({
      intervalMilliseconds: 1,
      loadSnapshot: async (signal) => {
        capturedSignal = signal
        return new Promise<PullRequestMergeReadiness>((resolve) => {
          finishRequest = () => resolve(RUNNING_SNAPSHOT)
        })
      },
      onSnapshot: () => undefined,
      onRefreshError: (message) => errors.push(message),
    })

    controller.start()
    await wait(5)
    controller.stop()
    finishRequest?.()
    await wait(5)

    expect(capturedSignal?.aborted).toBe(true)
    expect(errors).toEqual([])
  })

  test('reports a temporary refresh failure and continues polling', async () => {
    let calls = 0
    const errors: string[] = []
    const snapshots: PullRequestMergeReadiness[] = []
    const controller = new RunPollingController({
      intervalMilliseconds: 1,
      loadSnapshot: async () => {
        calls += 1
        if (calls === 1) {
          throw new Error('Could not reach the API.')
        }
        return COMPLETED_SNAPSHOT
      },
      onSnapshot: (snapshot) => snapshots.push(snapshot),
      onRefreshError: (message) => errors.push(message),
    })

    controller.start()
    await wait(100)

    expect(errors).toEqual(['Could not reach the API.'])
    expect(snapshots).toEqual([COMPLETED_SNAPSHOT])
    expect(calls).toBe(2)
    controller.stop()
  })

  test('stops retrying when a caller classifies a refresh error as permanent', async () => {
    let calls = 0
    const controller = new RunPollingController({
      intervalMilliseconds: 1,
      loadSnapshot: async () => {
        calls += 1
        throw new Error('No runtime run exists for this ID.')
      },
      onSnapshot: () => undefined,
      onRefreshError: () => undefined,
      shouldRetryError: () => false,
    })

    controller.start()
    await wait(15)

    expect(calls).toBe(1)
    controller.stop()
  })
})
