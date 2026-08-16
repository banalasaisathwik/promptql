import { useEffect, useState } from 'react'
import { fetchMergeReadinessRun } from './api'
import { ConnectorApiError } from './apiError'
import { RunPollingController } from './runPolling'
import type { PullRequestMergeReadiness } from './types'


export function useRunSnapshot(runId: string) {
  const [snapshot, setSnapshot] = useState<PullRequestMergeReadiness | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  useEffect(() => {
    setSnapshot(null)
    setLoading(true)
    setRefreshError(null)
    const polling = new RunPollingController({
      loadSnapshot: (signal) => fetchMergeReadinessRun(runId, signal),
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
  }, [runId])

  return { snapshot, loading, refreshError }
}
