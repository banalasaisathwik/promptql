import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { InvestigationConsolePage } from './InvestigationConsolePage'
import { buildInvestigationRequest, CHECKOUT_500_PRESET } from './investigationRequest'


test('renders question-first investigation controls and supporting context', () => {
  const markup = renderToStaticMarkup(<InvestigationConsolePage onRunStarted={() => undefined} />)

  expect(markup).toContain('What do you want to investigate?')
  expect(markup).toContain('Optional investigation context')
  expect(markup).toContain('Demo scenario')
  expect(markup).toContain('Checkout 500 after deployment')
  expect(markup).toContain('Repository owner')
  expect(markup).toContain('Incident ID')
  expect(markup).toContain('Deployment ID')
  expect(markup).toContain('Investigate')
})


test('requires a question before structured context can submit', () => {
  expect(buildInvestigationRequest({
    question: '   ',
    repository_owner: 'octo-org',
    repository_name: 'analytics',
    incident_reference: '',
    deployment_reference: '',
    pull_request_number: '',
    service: '',
    environment: '',
  })).toBe('What do you want to investigate? is required.')
})


test('checkout demo preset is a complete editable request draft', () => {
  expect(buildInvestigationRequest(CHECKOUT_500_PRESET)).toEqual({
    ...CHECKOUT_500_PRESET,
    pull_request_number: 42,
  })
})


test('builds the real structured API request from valid form values', () => {
  expect(buildInvestigationRequest({
    repository_owner: ' octo-org ',
    repository_name: ' analytics ',
    question: ' Why did checkout failures increase? ',
    incident_reference: ' incident:checkout-500 ',
    deployment_reference: '',
    pull_request_number: '42',
    service: 'checkout-api',
    environment: 'production',
  })).toEqual({
    repository_owner: 'octo-org',
    repository_name: 'analytics',
    question: 'Why did checkout failures increase?',
    incident_reference: 'incident:checkout-500',
    deployment_reference: null,
    pull_request_number: 42,
    service: 'checkout-api',
    environment: 'production',
  })
})
