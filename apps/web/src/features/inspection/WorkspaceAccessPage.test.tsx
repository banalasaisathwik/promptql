import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { ConnectToolsPage } from './ConnectToolsPage'
import { WorkspaceAuthPage } from './WorkspaceAuthPage'


test('renders the signup and login workspace form copy', () => {
  const signup = renderToStaticMarkup(
    <WorkspaceAuthPage initialMode="signup" onAuthenticated={() => undefined} onModeChanged={() => undefined} />,
  )
  const login = renderToStaticMarkup(
    <WorkspaceAuthPage initialMode="login" onAuthenticated={() => undefined} onModeChanged={() => undefined} />,
  )

  expect(signup).toContain('Create your workspace')
  expect(signup).toContain('Already have a workspace?')
  expect(login).toContain('Welcome back')
  expect(login).toContain('Need a workspace?')
  expect(signup).toContain('Whyline')
  expect(login).toContain('Want a quick look?')
  expect(login).toContain('demo@whyline.app')
  expect(login).toContain('whyline-demo-2026')
  expect(signup).not.toContain('Want a quick look?')
})


test('pre-fills the demo account into the visible login fields without auto-submitting', () => {
  const markup = renderToStaticMarkup(
    <WorkspaceAuthPage
      initialMode="login"
      initialEmail="demo@promptql.dev"
      initialPassword="correct horse battery staple"
      onAuthenticated={() => undefined}
      onModeChanged={() => undefined}
    />,
  )

  // Rendered as ordinary controlled-input values in a real <form> the
  // visitor must still submit themselves (ADR-035) -- static markup has no
  // way to auto-submit, so the values landing in the inputs is the proof.
  expect(markup).toContain('value="demo@promptql.dev"')
  expect(markup).toContain('value="correct horse battery staple"')
  expect(markup).toContain('<form')
})


test('renders the three credential connections, security note, and logout action', () => {
  const markup = renderToStaticMarkup(
    <ConnectToolsPage onContinue={() => undefined} onLoggedOut={() => undefined} />,
  )

  expect(markup).toContain('Connect your tools')
  expect(markup).toContain('GitHub')
  expect(markup).toContain('Jira')
  expect(markup).toContain('Sentry')
  expect(markup).toContain('Tokens are encrypted at rest and scoped to your workspace only.')
  expect(markup).toContain('Continue to investigations')
  expect(markup).toContain('Log out')
})
