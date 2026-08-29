import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  GroundingExtractionReview,
  InvestigationConsolePage,
} from './InvestigationConsolePage'
import {
  buildInvestigationRequest,
  CHECKOUT_500_PRESET,
  EMPTY_INVESTIGATION_FORM,
} from './investigationRequest'
import type { GroundingExtractionResponse } from './types'


test('renders the compact new-investigation flow without the retired marketing intro', () => {
  const markup = renderToStaticMarkup(<InvestigationConsolePage onRunStarted={() => undefined} />)

  expect(markup).toContain('NEW INVESTIGATION')
  expect(markup).toContain('What happened?')
  expect(markup).toContain('What do you want to investigate?')
  expect(markup).toContain('Demo scenario')
  expect(markup).toContain('Run demo investigation')
  expect(markup).toContain('Checkout 500 after deployment')
  expect(markup).toContain('Fill in repository, incident, deployment, PR from description')
  expect(markup).not.toContain('Investigate an engineering issue')
  expect(markup).not.toContain('Grounded investigation')
  expect(markup).not.toContain('PromptQL uses')
  expect(markup).not.toContain('Optional investigation context')
})


test('keeps the extraction confirmation separate from starting an investigation', () => {
  const markup = renderToStaticMarkup(<InvestigationConsolePage onRunStarted={() => undefined} />)

  expect(markup).not.toContain('Confirm &amp; Investigate')
  expect(markup).not.toContain('Detected from your description')
})


test('shows an extraction clarification and enables confirmation after an anchor is filled manually', () => {
  const extraction: GroundingExtractionResponse = {
    status: 'needs_clarification',
    extracted: {
      repository_owner: 'octo-org',
      repository_name: 'analytics',
      incident_reference: null,
      deployment_reference: null,
      pull_request_number: null,
    },
    missing: ['incident_reference', 'deployment_reference', 'pull_request_number'],
    question: 'Which incident, deployment, or pull request is this about?',
  }
  const form = {
    ...EMPTY_INVESTIGATION_FORM,
    question: 'Checkout is failing after a deploy.',
    repository_owner: 'octo-org',
    repository_name: 'analytics',
  }

  const needsClarification = renderToStaticMarkup(
    <GroundingExtractionReview
      extraction={extraction}
      form={form}
      submitting={false}
      onUpdate={() => undefined}
    />,
  )
  const manuallyAnchored = renderToStaticMarkup(
    <GroundingExtractionReview
      extraction={extraction}
      form={{ ...form, incident_reference: 'incident:checkout-500' }}
      submitting={false}
      onUpdate={() => undefined}
    />,
  )

  expect(needsClarification).toContain('More information needed.')
  expect(needsClarification).toContain(extraction.question)
  expect(needsClarification).toMatch(
    /<button class="primary-action" type="submit" disabled="">Confirm &amp; Investigate/,
  )
  expect(manuallyAnchored).toMatch(
    /<button class="primary-action" type="submit">Confirm &amp; Investigate/,
  )
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
