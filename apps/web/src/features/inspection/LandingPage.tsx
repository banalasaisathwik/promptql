import { useState } from 'react'
import { fetchDemoAccount } from './api'
import { ConnectorApiError } from './apiError'
import { AccessHeader } from './WorkspaceAuthPage'
import './workspaceAccess.css'
import './landingPage.css'


export function LandingPage({
  onTryDemo,
  onExploreAnonymously,
}: {
  onTryDemo: (email: string, password: string) => void
  onExploreAnonymously: () => void
}) {
  const [loadingDemo, setLoadingDemo] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function tryDemo() {
    if (loadingDemo) return
    setLoadingDemo(true)
    setError(null)
    try {
      const demoAccount = await fetchDemoAccount()
      onTryDemo(demoAccount.email, demoAccount.password)
    } catch (caught) {
      setError(
        caught instanceof ConnectorApiError
          ? caught.message
          : 'Could not load the demo account right now.',
      )
    } finally {
      setLoadingDemo(false)
    }
  }

  return (
    <main className="workspace-access-shell">
      <AccessHeader />
      <section className="landing-hero">
        <h1>Find out why your deploy broke — before your team asks.</h1>
        <p className="landing-lede">
          PromptQL investigates a failing deploy the way an engineer would:
          it reads the pull request, the incident, and the deployment
          history together, and explains what happened with evidence it can
          point to in your own systems — not a plausible-sounding guess.
        </p>
        <p className="landing-description">
          Connect GitHub, Jira, and Sentry, ask what broke, and get a
          grounded root-cause explanation citing the exact commit, failing
          line, and ticket involved.
        </p>
        <div className="landing-actions">
          <button
            className="workspace-primary-button"
            type="button"
            onClick={() => void tryDemo()}
            disabled={loadingDemo}
          >
            {loadingDemo ? 'Loading demo…' : 'Try the Demo →'}
          </button>
          <button
            className="landing-secondary-link"
            type="button"
            disabled={loadingDemo}
            onClick={onExploreAnonymously}
          >
            Or explore without an account
          </button>
        </div>
        {error && <p className="workspace-access-error" role="alert">{error}</p>}
        <div className="landing-preview" aria-label="What a PromptQL investigation looks like">
          <p className="landing-preview-step"><strong>Incident</strong> Checkout 500s spike after the 2:14pm deploy</p>
          <p className="landing-preview-step"><strong>Deploy</strong> PR #482 merged 6 minutes earlier, touching the checkout service</p>
          <p className="landing-preview-step"><strong>Evidence</strong> The changed line matches the failing stack frame</p>
          <p className="landing-preview-step"><strong>Answer</strong> A grounded explanation, citing the commit and file — not a guess</p>
        </div>
      </section>
    </main>
  )
}
