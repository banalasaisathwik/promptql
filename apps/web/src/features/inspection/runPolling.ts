import type { PullRequestMergeReadiness } from './types'


export function isTerminalRun(run: PullRequestMergeReadiness): boolean {
  return (
    run.status === 'completed' ||
    run.status === 'failed' ||
    run.status === 'cancelled'
  )
}


type SnapshotLoader = (
  signal: AbortSignal,
) => Promise<PullRequestMergeReadiness>


interface RunPollingControllerOptions {
  loadSnapshot: SnapshotLoader
  onSnapshot: (snapshot: PullRequestMergeReadiness) => void
  onRefreshError: (message: string) => void
  shouldRetryError?: (error: unknown) => boolean
  intervalMilliseconds?: number
}


export class RunPollingController {
  private readonly loadSnapshot: SnapshotLoader
  private readonly onSnapshot: (snapshot: PullRequestMergeReadiness) => void
  private readonly onRefreshError: (message: string) => void
  private readonly intervalMilliseconds: number
  private readonly shouldRetryError: (error: unknown) => boolean
  private timeoutId: ReturnType<typeof setTimeout> | null = null
  private requestController: AbortController | null = null
  private stopped = false
  private requestInFlight = false

  constructor(options: RunPollingControllerOptions) {
    this.loadSnapshot = options.loadSnapshot
    this.onSnapshot = options.onSnapshot
    this.onRefreshError = options.onRefreshError
    this.intervalMilliseconds = options.intervalMilliseconds ?? 1_000
    this.shouldRetryError = options.shouldRetryError ?? (() => true)
  }

  start(): void {
    this.schedule(0)
  }

  stop(): void {
    this.stopped = true
    if (this.timeoutId !== null) {
      clearTimeout(this.timeoutId)
      this.timeoutId = null
    }
    this.requestController?.abort()
  }

  private schedule(delayMilliseconds: number): void {
    if (this.stopped || this.timeoutId !== null) {
      return
    }
    this.timeoutId = setTimeout(() => {
      this.timeoutId = null
      void this.refresh()
    }, delayMilliseconds)
  }

  private async refresh(): Promise<void> {
    if (this.stopped || this.requestInFlight) {
      return
    }
    this.requestInFlight = true
    const controller = new AbortController()
    this.requestController = controller
    try {
      const snapshot = await this.loadSnapshot(controller.signal)
      if (this.stopped) {
        return
      }
      this.onSnapshot(snapshot)
      if (!isTerminalRun(snapshot)) {
        this.schedule(this.intervalMilliseconds)
      }
    } catch (error) {
      if (!this.stopped && !controller.signal.aborted) {
        this.onRefreshError(
          error instanceof Error
            ? error.message
            : 'The dashboard could not refresh this run.',
        )
        if (this.shouldRetryError(error)) {
          this.schedule(this.intervalMilliseconds)
        }
      }
    } finally {
      this.requestInFlight = false
      if (this.requestController === controller) {
        this.requestController = null
      }
    }
  }
}
