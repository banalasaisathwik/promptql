import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  connectCredential,
  disconnectCredential,
  fetchCredentialConnections,
  logoutWorkspace,
} from './api'
import type { CredentialConnections, CredentialProvider } from './api'
import { ConnectorApiError } from './apiError'
import { AccessHeader } from './WorkspaceAuthPage'
import './workspaceAccess.css'


const PROVIDERS: Array<{ provider: CredentialProvider, label: string, icon: string }> = [
  { provider: 'github', label: 'GitHub', icon: 'GH' },
  { provider: 'jira', label: 'Jira', icon: 'J' },
  { provider: 'sentry', label: 'Sentry', icon: 'S' },
]


export function ConnectToolsPage({
  onContinue,
  onLoggedOut,
}: {
  onContinue: () => void
  onLoggedOut: () => void
}) {
  const [connections, setConnections] = useState<CredentialConnections | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editingProvider, setEditingProvider] = useState<CredentialProvider | null>(null)
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    void loadConnections()
  }, [])

  async function loadConnections() {
    setError(null)
    try {
      setConnections(await fetchCredentialConnections())
    } catch (caught) {
      setError(caught instanceof ConnectorApiError ? caught.message : 'Could not load connections.')
    }
  }

  function openTokenForm(provider: CredentialProvider) {
    setEditingProvider(provider)
    setToken('')
    setError(null)
  }

  async function saveCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editingProvider || saving) return

    setSaving(true)
    setError(null)
    try {
      await connectCredential(editingProvider, token)
      setConnections((current) => current && {
        ...current,
        [editingProvider]: { connected: true, source: 'real' },
      })
      setEditingProvider(null)
      setToken('')
    } catch (caught) {
      setError(caught instanceof ConnectorApiError ? caught.message : 'Could not connect this tool.')
    } finally {
      setSaving(false)
    }
  }

  async function removeCredential(provider: CredentialProvider) {
    if (saving) return

    setSaving(true)
    setError(null)
    try {
      await disconnectCredential(provider)
      setConnections((current) => current && {
        ...current,
        [provider]: { connected: false, source: 'real' },
      })
    } catch (caught) {
      setError(caught instanceof ConnectorApiError ? caught.message : 'Could not disconnect this tool.')
    } finally {
      setSaving(false)
    }
  }

  async function logout() {
    if (saving) return

    setSaving(true)
    setError(null)
    try {
      await logoutWorkspace()
      onLoggedOut()
    } catch (caught) {
      setError(caught instanceof ConnectorApiError ? caught.message : 'Could not log out.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="workspace-access-shell">
      <AccessHeader>
        <button className="workspace-logout" type="button" onClick={() => void logout()}>
          Log out
        </button>
      </AccessHeader>
      <section className="workspace-connect-card" aria-labelledby="connect-tools-title">
        <div className="workspace-access-heading">
          <h1 id="connect-tools-title">Connect your tools</h1>
          <p>
            PromptQL investigates using real data from systems you already use.
            Nothing is read until you ask a question.
          </p>
        </div>
        {error && <p className="workspace-access-error" role="alert">{error}</p>}
        <div className="workspace-connection-list" aria-live="polite">
          {PROVIDERS.map(({ provider, label, icon }) => {
            const status = connections?.[provider]
            const connected = status?.connected ?? false
            const isDemo = status?.source === 'demo'
            const isEditing = editingProvider === provider
            return (
              <article className="workspace-connection-row" key={provider}>
                <div className="workspace-connection-summary">
                  <span className="workspace-provider-icon" aria-hidden="true">{icon}</span>
                  <div>
                    <h2>{label}</h2>
                    <p className={connected ? 'workspace-status-connected' : undefined}>
                      {connections === null
                        ? 'Checking connection…'
                        : connected
                          ? isDemo
                            ? 'Connected — Demo Data'
                            : 'Connected'
                          : 'Not connected · optional'}
                    </p>
                  </div>
                </div>
                {!isDemo && (connected ? (
                  <button
                    className="workspace-secondary-button"
                    type="button"
                    disabled={saving}
                    onClick={() => void removeCredential(provider)}
                  >
                    Disconnect
                  </button>
                ) : (
                  <button
                    className="workspace-primary-button workspace-row-button"
                    type="button"
                    disabled={connections === null || saving}
                    onClick={() => openTokenForm(provider)}
                  >
                    Connect
                  </button>
                ))}
                {isEditing && (
                  <form className="workspace-token-form" onSubmit={saveCredential}>
                    <label>
                      {label} personal access token
                      <input
                        type="password"
                        autoComplete="off"
                        value={token}
                        onChange={(event) => setToken(event.target.value)}
                        placeholder="Paste your token"
                        required
                      />
                    </label>
                    <div>
                      <button className="workspace-primary-button" type="submit" disabled={saving}>
                        {saving ? 'Connecting…' : 'Save connection'}
                      </button>
                      <button
                        className="workspace-text-button"
                        type="button"
                        disabled={saving}
                        onClick={() => { setEditingProvider(null); setToken('') }}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                )}
              </article>
            )
          })}
        </div>
        <footer className="workspace-connect-footer">
          <p>Tokens are encrypted at rest and scoped to your workspace only.</p>
          <button className="workspace-primary-button" type="button" onClick={onContinue}>
            Continue to investigations →
          </button>
        </footer>
      </section>
    </main>
  )
}
