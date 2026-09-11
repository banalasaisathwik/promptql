import { useEffect, useState } from 'react'
import { fetchCurrentUser } from './features/inspection/api'
import type { AuthenticatedUser } from './features/inspection/api'
import { ConnectorApiError } from './features/inspection/apiError'
import { AuthPage, Landing, WhylineWorkspace } from './features/inspection/WhylineApp'
import './App.css'

/** The V1 shell owns only browser routing and the cookie-backed auth boot state. */
function App() {
  const [pathname, setPathname] = useState(window.location.pathname)
  const [user, setUser] = useState<AuthenticatedUser | null>(null)
  const [authState, setAuthState] = useState<'loading' | 'authenticated' | 'unauthenticated'>('loading')

  function navigate(path: string) {
    window.history.pushState(null, '', path)
    setPathname(path)
  }

  useEffect(() => {
    const updatePath = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', updatePath)
    return () => window.removeEventListener('popstate', updatePath)
  }, [])

  useEffect(() => {
    void fetchCurrentUser().then((currentUser) => {
      setUser(currentUser)
      setAuthState('authenticated')
    }).catch((caught) => {
      // A workspace is never rendered until the server resolves its session.
      if (!(caught instanceof ConnectorApiError) || caught.status === 401) setAuthState('unauthenticated')
      else setAuthState('unauthenticated')
    })
  }, [])

  if (authState === 'loading') return <main className="wl-boot" aria-live="polite">Loading Whyline…</main>
  if (pathname === '/') return <Landing navigate={navigate} />
  if (pathname === '/login' || pathname === '/signup') {
    return <AuthPage mode={pathname === '/login' ? 'login' : 'signup'} navigate={navigate} onAuthenticated={(currentUser) => { setUser(currentUser); setAuthState('authenticated'); navigate('/connect') }} />
  }
  if (!user) return <AuthPage mode="login" navigate={navigate} onAuthenticated={(currentUser) => { setUser(currentUser); setAuthState('authenticated'); navigate('/connect') }} />
  const page = pathname === '/sources' ? 'sources' : pathname === '/connect' ? 'connect' : 'scan'
  return <WhylineWorkspace user={user} page={page} navigate={navigate} onLogout={() => { setUser(null); setAuthState('unauthenticated'); navigate('/') }} />
}

export default App
