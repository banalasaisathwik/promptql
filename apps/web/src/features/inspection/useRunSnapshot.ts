import { useEffect, useState } from 'react'
import { fetchRuntimeRun } from './api'
import { ConnectorApiError } from './apiError'
import { RunPollingController } from './runPolling'
import type { RuntimeRun } from './types'


export function useRunSnapshot(runId: string) {
  const [snapshot, setSnapshot] = useState<RuntimeRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  // Accepting a follow-up (ADR-033) reopens an investigation from completed
  // back to running, after RunPollingController has already stopped polling
  // because it saw a terminal status. Bumping this generation recreates the
  // controller so polling resumes; it intentionally does not clear the
  // existing snapshot, so the dashboard keeps showing the prior result while
  // the follow-up round runs.
  const [pollGeneration, setPollGeneration] = useState(0)

  useEffect(() => {
    setSnapshot(null)
    setLoading(true)
    setRefreshError(null)
  }, [runId])

  useEffect(() => {
    const polling = new RunPollingController({
      loadSnapshot: (signal) => fetchRuntimeRun(runId, signal),
      onSnapshot: (nextSnapshot) => {
        setSnapshot(nextSnapshot)
        setLoading(false)
        setRefreshError(null)
      },
      onRefreshError: (message) => {
        setLoading(false)
        setRefreshError(message)
      },
      shouldRetryError: (error) =>
        !(error instanceof ConnectorApiError && error.status === 404),
    })
    polling.start()
    return () => polling.stop()
  }, [runId, pollGeneration])

  function resumePolling(): void {
    setPollGeneration((generation) => generation + 1)
  }

  return { snapshot, loading, refreshError, resumePolling }
}
