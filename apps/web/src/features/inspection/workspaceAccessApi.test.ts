import { afterEach, expect, test } from 'bun:test'
import {
  connectCredential,
  disconnectCredential,
  fetchCredentialConnections,
  fetchDemoAccount,
  loginWorkspace,
  logoutWorkspace,
  registerWorkspace,
} from './api'


const originalFetch = globalThis.fetch


afterEach(() => {
  globalThis.fetch = originalFetch
})


test('registers a workspace through the session-aware auth endpoint', async () => {
  let requestUrl = ''
  let requestInit: RequestInit | undefined
  globalThis.fetch = (async (url, init) => {
    requestUrl = String(url)
    requestInit = init
    return new Response(JSON.stringify({
      id: 'a9e3c5d3-c089-4b5e-a006-63f1a3e66a3a',
      email: 'new@example.com',
      created_at: '2026-08-28T10:00:00Z',
    }), { status: 201 })
  }) as typeof fetch

  const user = await registerWorkspace('new@example.com', 'correct horse battery staple')

  expect(requestUrl).toBe('/v1/auth/register')
  expect(JSON.parse(String(requestInit?.body))).toEqual({
    email: 'new@example.com', password: 'correct horse battery staple',
  })
  expect(requestInit?.credentials).toBe('include')
  expect(user.email).toBe('new@example.com')
})


test('surfaces the backend duplicate-email message from registration', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({
    code: 'user_already_exists', message: 'An account with this email already exists.',
  }), { status: 409 })) as typeof fetch

  await expect(registerWorkspace('duplicate@example.com', 'correct horse battery staple'))
    .rejects.toThrow('An account with this email already exists.')
})


test('surfaces FastAPI validation messages from registration unchanged', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({
    detail: [{ type: 'string_too_short', msg: 'String should have at least 8 characters' }],
  }), { status: 422 })) as typeof fetch

  await expect(registerWorkspace('new@example.com', 'short'))
    .rejects.toThrow('String should have at least 8 characters')
})


test('logs in through the session-aware auth endpoint and surfaces wrong-password errors', async () => {
  let requestUrl = ''
  let requestInit: RequestInit | undefined
  globalThis.fetch = (async (url, init) => {
    requestUrl = String(url)
    requestInit = init
    return new Response(JSON.stringify({
      code: 'invalid_credentials', message: 'Incorrect email or password.',
    }), { status: 401 })
  }) as typeof fetch

  await expect(loginWorkspace('user@example.com', 'incorrect password'))
    .rejects.toThrow('Incorrect email or password.')
  expect(requestUrl).toBe('/v1/auth/login')
  expect(JSON.parse(String(requestInit?.body))).toEqual({
    email: 'user@example.com', password: 'incorrect password',
  })
  expect(requestInit?.credentials).toBe('include')
})


test('connects, reloads, disconnects, and logs out through the credential endpoints', async () => {
  const calls: Array<{ url: string, init?: RequestInit }> = []
  globalThis.fetch = (async (url, init) => {
    calls.push({ url: String(url), init })
    if (String(url) === '/v1/credentials' && init?.method === 'POST') {
      return new Response(JSON.stringify({ provider: 'github', connected: true }), { status: 200 })
    }
    if (String(url) === '/v1/credentials') {
      return new Response(JSON.stringify({ providers: [
        { provider: 'github', connected: true, source: 'real' },
        { provider: 'jira', connected: false, source: 'real' },
        { provider: 'sentry', connected: false, source: 'real' },
      ] }), { status: 200 })
    }
    return new Response(null, { status: 204 })
  }) as typeof fetch

  await connectCredential('github', 'test-github-token')
  expect(await fetchCredentialConnections()).toEqual({
    github: { connected: true, source: 'real' },
    jira: { connected: false, source: 'real' },
    sentry: { connected: false, source: 'real' },
  })
  await disconnectCredential('github')
  await logoutWorkspace()

  expect(calls.map((call) => call.url)).toEqual([
    '/v1/credentials', '/v1/credentials', '/v1/credentials/github', '/v1/auth/logout',
  ])
  expect(JSON.parse(String(calls[0].init?.body))).toEqual({
    provider: 'github', token: 'test-github-token',
  })
  expect(calls.every((call) => call.init?.credentials === 'include')).toBe(true)
})


test('fetches the public demo-account email and password unauthenticated', async () => {
  let requestUrl = ''
  globalThis.fetch = (async (url) => {
    requestUrl = String(url)
    return new Response(JSON.stringify({
      email: 'demo@promptql.dev', password: 'correct horse battery staple',
    }), { status: 200 })
  }) as typeof fetch

  const demoAccount = await fetchDemoAccount()

  expect(requestUrl).toBe('/v1/demo-account')
  expect(demoAccount).toEqual({
    email: 'demo@promptql.dev', password: 'correct horse battery staple',
  })
})
