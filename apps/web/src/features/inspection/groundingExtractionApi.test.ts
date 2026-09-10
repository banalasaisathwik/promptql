import { afterEach, expect, test } from 'bun:test'
import { extractGrounding, startInvestigationRun } from './api'
import { buildInvestigationRequest, EMPTY_INVESTIGATION_FORM } from './investigationRequest'


const originalFetch = globalThis.fetch


afterEach(() => {
  globalThis.fetch = originalFetch
})


test('extracts a complete grounding proposal from a known text sample', async () => {
  let requestInit: RequestInit | undefined
  globalThis.fetch = (async (_url, init) => {
    requestInit = init
    return new Response(JSON.stringify({
    status: 'complete',
    extracted: {
      repository_owner: 'octo-org',
      repository_name: 'analytics',
      incident_reference: null,
      deployment_reference: 'deployment:52',
      pull_request_number: 42,
    },
    missing: [],
    question: null,
  }), { status: 200 })
  }) as typeof fetch

  const response = await extractGrounding({
    description: 'PR 42 in octo-org/analytics, deployment 52, checkout throwing errors',
  })

  expect(response.status).toBe('complete')
  expect(response.extracted.repository_owner).toBe('octo-org')
  expect(response.extracted.pull_request_number).toBe(42)
  expect(response.missing).toEqual([])
  expect(requestInit?.cache).toBe('no-store')
})


test('reports needs_clarification with a question for ambiguous text', async () => {
  globalThis.fetch = (async () => new Response(JSON.stringify({
    status: 'needs_clarification',
    extracted: {
      repository_owner: null,
      repository_name: null,
      incident_reference: null,
      deployment_reference: null,
      pull_request_number: null,
    },
    missing: ['incident_reference', 'deployment_reference', 'pull_request_number'],
    question: 'Which incident, deployment, or pull request is this about?',
  }), { status: 200 })) as typeof fetch

  const response = await extractGrounding({
    description: 'Checkout is throwing errors after a deploy went out.',
  })

  expect(response.status).toBe('needs_clarification')
  expect(response.missing).toContain('pull_request_number')
  expect(response.question).not.toBeNull()
})


test('confirm-then-submit: extracted fields flow into the unchanged start-investigation call', async () => {
  let extractRequestBody = ''
  let submitRequestBody = ''
  let submitUrl = ''
  let call = 0

  globalThis.fetch = (async (url, init) => {
    call += 1
    if (call === 1) {
      extractRequestBody = String(init?.body)
      return new Response(JSON.stringify({
        status: 'complete',
        extracted: {
          repository_owner: 'octo-org',
          repository_name: 'analytics',
          incident_reference: null,
          deployment_reference: 'deployment:52',
          pull_request_number: 42,
        },
        missing: [],
        question: null,
      }), { status: 200 })
    }
    submitUrl = String(url)
    submitRequestBody = String(init?.body)
    return new Response(JSON.stringify({ run_id: 'run-1', status: 'pending' }), { status: 202 })
  }) as typeof fetch

  // Step 1: the user describes the incident in plain English and the page
  // calls the new extraction endpoint.
  const description = 'PR 42 in octo-org/analytics, deployment 52, checkout throwing errors'
  const extraction = await extractGrounding({ description })

  expect(JSON.parse(extractRequestBody)).toEqual({ description })
  expect(extraction.status).toBe('complete')

  // Step 2: the page fills the structured form with what was extracted, the
  // user reviews/edits it (here, corrects the deployment reference), then
  // confirms by submitting through the existing, unchanged endpoint.
  const reviewedForm = {
    ...EMPTY_INVESTIGATION_FORM,
    question: description,
    repository_owner: extraction.extracted.repository_owner ?? '',
    repository_name: extraction.extracted.repository_name ?? '',
    incident_reference: extraction.extracted.incident_reference ?? '',
    deployment_reference: 'deployment:corrected-52',
    pull_request_number: String(extraction.extracted.pull_request_number ?? ''),
  }
  const request = buildInvestigationRequest(reviewedForm)
  if (typeof request === 'string') {
    throw new Error(`expected a valid request, got error: ${request}`)
  }
  await startInvestigationRun(request)

  expect(submitUrl).toBe('/v1/investigations')
  const submittedBody = JSON.parse(submitRequestBody)
  expect(submittedBody.repository_owner).toBe('octo-org')
  expect(submittedBody.pull_request_number).toBe(42)
  // The user's correction after reviewing the extraction wins over the
  // originally extracted value — confirmation means the user, not the
  // extractor, has final control before a run is ever started.
  expect(submittedBody.deployment_reference).toBe('deployment:corrected-52')
})
