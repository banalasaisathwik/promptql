import { useEffect, useState } from 'react'
import { fetchRuntimeRun } from './api'
import { ConnectorApiError } from './apiError'
import { RunPollingController } from './runPolling'
import type { RuntimeRun } from './types'


export function useRunSnapshot(runId: string) {
  const [snapshot, setSnapshot] = useState<RuntimeRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  useEffect(() => {
    setSnapshot(null)
    setLoading(true)
    setRefreshError(null)
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
  }, [runId])

  return { snapshot, loading, refreshError }
}
