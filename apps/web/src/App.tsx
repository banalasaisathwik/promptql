/** Root React component.
 *
 * App deliberately contains no feature logic. It selects the page to render,
 * while the readiness feature owns its state, API calls, and presentation.
 */

import './App.css'
import { useEffect, useState } from 'react'
import { InvestigationConsolePage } from './features/inspection/InvestigationConsolePage'
import { InvestigationTraceView } from './features/inspection/InvestigationTraceView'
import { LandingPage } from './features/inspection/LandingPage'
import { RunDashboardPage } from './features/inspection/RunDashboardPage'
import { ConnectToolsPage } from './features/inspection/ConnectToolsPage'
import { WorkspaceAuthPage } from './features/inspection/WorkspaceAuthPage'
import { runTracePathFor } from './routing'


function runIdFromPath(pathname: string): string | null {
  const match = /^\/runs\/([^/]+)$/.exec(pathname)
  return match ? decodeURIComponent(match[1]) : null
}


function traceRunIdFromPath(pathname: string): string | null {
  const match = /^\/runs\/([^/]+)\/trace$/.exec(pathname)
  return match ? decodeURIComponent(match[1]) : null
}


function App() {
  const [pathname, setPathname] = useState(window.location.pathname)
  const [demoPrefill, setDemoPrefill] = useState<{ email: string, password: string } | null>(null)
  const traceRunId = traceRunIdFromPath(pathname)
  const runId = runIdFromPath(pathname)

  function navigate(nextPath: string) {
    window.history.pushState(null, '', nextPath)
    setPathname(nextPath)
  }

  useEffect(() => {
    function updatePathname() {
      setPathname(window.location.pathname)
    }
    window.addEventListener('popstate', updatePathname)
    return () => window.removeEventListener('popstate', updatePathname)
  }, [])

  if (traceRunId) {
    return <InvestigationTraceView runId={traceRunId} />
  }

  if (runId) {
    return <RunDashboardPage runId={runId} />
  }

  if (pathname === '/') {
    return (
      <LandingPage
        onTryDemo={(email, password) => {
          setDemoPrefill({ email, password })
          navigate('/login')
        }}
        onExploreAnonymously={() => navigate('/console')}
      />
    )
  }

  if (pathname === '/signup' || pathname === '/login') {
    return (
      <WorkspaceAuthPage
        initialMode={pathname === '/login' ? 'login' : 'signup'}
        initialEmail={pathname === '/login' ? demoPrefill?.email : undefined}
        initialPassword={pathname === '/login' ? demoPrefill?.password : undefined}
        onAuthenticated={() => {
          setDemoPrefill(null)
          navigate('/connect')
        }}
        onModeChanged={(mode) => navigate(mode === 'login' ? '/login' : '/signup')}
      />
    )
  }

  if (pathname === '/connect') {
    return (
      <ConnectToolsPage
        onContinue={() => navigate('/console')}
        onLoggedOut={() => navigate('/login')}
      />
    )
  }

  // The console is shared by anonymous visitors and authenticated workspaces.
  // Its existing demo action submits the same checkout-500 fixture for both.
  return (
    <InvestigationConsolePage
      onRunStarted={(nextRunId) => {
        navigate(runTracePathFor(nextRunId))
      }}
    />
  )
}


export default App
