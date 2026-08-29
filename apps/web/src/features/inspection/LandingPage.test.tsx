import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { LandingPage } from './LandingPage'


test('renders the headline, product description, and both entry points', () => {
  const markup = renderToStaticMarkup(
    <LandingPage onTryDemo={() => undefined} onExploreAnonymously={() => undefined} />,
  )

  expect(markup).toContain('Whyline')
  expect(markup).toContain('Try the Demo')
  expect(markup).toContain('Or explore without an account')
  expect(markup).toContain('Connect GitHub, Jira, and Sentry')
})
