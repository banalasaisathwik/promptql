import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { InvestigationConsolePage } from './InvestigationConsolePage'
import { buildInvestigationRequest } from './investigationRequest'


test('renders structured investigation fields and submit action', () => {
  const markup = renderToStaticMarkup(<InvestigationConsolePage onRunStarted={() => undefined} />)

  expect(markup).toContain('Repository owner')
  expect(markup).toContain('Incident ID')
  expect(markup).toContain('Deployment ID')
  expect(markup).toContain('Incident summary')
  expect(markup).toContain('Investigate')
})


test('builds the real structured API request from valid form values', () => {
  expect(buildInvestigationRequest({
    repository_owner: ' octo-org ',
    repository_name: ' analytics ',
    incident_summary: ' Checkout failures increased. ',
    incident_reference: ' incident:checkout-500 ',
    deployment_reference: '',
    pull_request_number: '42',
    service: 'checkout-api',
    environment: 'production',
  })).toEqual({
    repository_owner: 'octo-org',
    repository_name: 'analytics',
    incident_summary: 'Checkout failures increased.',
    incident_reference: 'incident:checkout-500',
    deployment_reference: null,
    pull_request_number: 42,
    service: 'checkout-api',
    environment: 'production',
  })
})
