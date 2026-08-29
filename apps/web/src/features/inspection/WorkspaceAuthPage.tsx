import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { ReactNode } from 'react'
import { ConnectorApiError } from './apiError'
import { loginWorkspace, registerWorkspace } from './api'
import './workspaceAccess.css'


type AuthMode = 'signup' | 'login'


export function WorkspaceAuthPage({
  initialMode,
  initialEmail,
  initialPassword,
  onAuthenticated,
  onModeChanged,
}: {
  initialMode: AuthMode
  initialEmail?: string
  initialPassword?: string
  onAuthenticated: () => void
  onModeChanged: (mode: AuthMode) => void
}) {
  const [mode, setMode] = useState<AuthMode>(initialMode)
  // Pre-filled but never auto-submitted (ADR-035): the demo account's
  // credentials land here from the landing page's "Try the Demo" button so
  // the visitor still sees and submits a real login themselves.
  const [email, setEmail] = useState(initialEmail ?? '')
  const [password, setPassword] = useState(initialPassword ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setMode(initialMode)
    setError(null)
  }, [initialMode])

  useEffect(() => {
    if (initialEmail !== undefined) setEmail(initialEmail)
    if (initialPassword !== undefined) setPassword(initialPassword)
  }, [initialEmail, initialPassword])

  const isLogin = mode === 'login'

  function changeMode(nextMode: AuthMode) {
    setMode(nextMode)
    setError(null)
    onModeChanged(nextMode)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return

    setSubmitting(true)
    setError(null)
    try {
      if (isLogin) {
        await loginWorkspace(email, password)
      } else {
        await registerWorkspace(email, password)
      }
      onAuthenticated()
    } catch (caught) {
      setError(
        caught instanceof ConnectorApiError
          ? caught.message
          : 'The workspace request could not be completed.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="workspace-access-shell">
      <AccessHeader />
      <section className="workspace-auth-card" aria-labelledby="workspace-auth-title">
        <div className="workspace-access-heading">
          <h1 id="workspace-auth-title">
            {isLogin ? 'Welcome back' : 'Create your workspace'}
          </h1>
          <p>
            One account, your own connected tools, your own investigations —
            nothing is shared across workspaces.
          </p>
        </div>
        {isLogin && (
          <p className="workspace-demo-hint">
            <strong>Want a quick look?</strong> Log in with{' '}
            <strong>demo@whyline.app</strong> /{' '}
            <strong>whyline-demo-2026</strong> — everything comes pre-connected
            with sample data.
          </p>
        )}
        <form onSubmit={submit} className="workspace-access-form">
          <label>
            Email
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete={isLogin ? 'current-password' : 'new-password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && <p className="workspace-access-error" role="alert">{error}</p>}
          <button className="workspace-primary-button" type="submit" disabled={submitting}>
            {submitting
              ? 'Please wait…'
              : isLogin
                ? 'Log in →'
                : 'Create account →'}
          </button>
        </form>
        <p className="workspace-auth-toggle">
          {isLogin ? 'Need a workspace? ' : 'Already have a workspace? '}
          <button
            type="button"
            className="workspace-text-button"
            onClick={() => changeMode(isLogin ? 'signup' : 'login')}
          >
            {isLogin ? 'Sign up' : 'Log in'}
          </button>
        </p>
      </section>
    </main>
  )
}


export function AccessHeader({
  children,
}: {
  children?: ReactNode
}) {
  return (
    <header className="workspace-access-header">
      <a className="whyline-brand" href="/" aria-label="Whyline home">
        <span className="whyline-brand-mark" aria-hidden="true">W</span>
        <span>Whyline</span>
      </a>
      {children}
    </header>
  )
}
