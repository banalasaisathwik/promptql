/** Root React component.
 *
 * App deliberately contains no feature logic. It selects the page to render,
 * while the readiness feature owns its state, API calls, and presentation.
 */

import './App.css'
import { useEffect, useState } from 'react'
import { MergeReadinessPage } from './features/inspection/MergeReadinessPage'
import { RunDashboardPage } from './features/inspection/RunDashboardPage'
import { runPathFor } from './routing'


function runIdFromPath(pathname: string): string | null {
  const match = /^\/runs\/([^/]+)$/.exec(pathname)
  return match ? decodeURIComponent(match[1]) : null
}


function App() {
  const [pathname, setPathname] = useState(window.location.pathname)
  const runId = runIdFromPath(pathname)

  useEffect(() => {
    function updatePathname() {
      setPathname(window.location.pathname)
    }
    window.addEventListener('popstate', updatePathname)
    return () => window.removeEventListener('popstate', updatePathname)
  }, [])

  if (runId) {
    return <RunDashboardPage runId={runId} />
  }

  return (
    <MergeReadinessPage
      onLiveRunStarted={(nextRunId) => {
        const nextPath = runPathFor(nextRunId)
        window.history.pushState(null, '', nextPath)
        setPathname(nextPath)
      }}
    />
  )
}


export default App
