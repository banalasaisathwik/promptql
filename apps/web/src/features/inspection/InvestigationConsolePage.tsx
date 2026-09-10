import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { GroundingExtractionResponse } from './types'
import { extractGrounding, startInvestigationRun } from './api'
import { ConnectorApiError } from './apiError'
import {
  buildInvestigationRequest,
  CHECKOUT_500_PRESET,
  EMPTY_INVESTIGATION_FORM,
  formHasRequiredGroundingReference,
} from './investigationRequest'


export function GroundingExtractionReview({
  extraction,
  form,
  submitting,
  onUpdate,
}: {
  extraction: GroundingExtractionResponse
  form: typeof EMPTY_INVESTIGATION_FORM
  submitting: boolean
  onUpdate: (field: keyof typeof EMPTY_INVESTIGATION_FORM, value: string) => void
}) {
  const confirmationDisabled = submitting || !formHasRequiredGroundingReference(form)

  return (
    <section className="run-card" aria-live="polite">
      <p className="result-section-label">
        Detected from your description — review before continuing
      </p>
      {extraction.status === 'needs_clarification' && extraction.question && (
        <p className="inline-alert" role="status">
          <strong>More information needed.</strong> {extraction.question}
        </p>
      )}
      <ul className="plain-list">
        <li>
          <label>
            <span className="trace-log-tag trace-log-tag--fact">repository owner</span>
            <input
              value={form.repository_owner}
              onChange={(event) => onUpdate('repository_owner', event.target.value)}
              placeholder="Not detected"
            />
          </label>
        </li>
        <li>
          <label>
            <span className="trace-log-tag trace-log-tag--fact">repository name</span>
            <input
              value={form.repository_name}
              onChange={(event) => onUpdate('repository_name', event.target.value)}
              placeholder="Not detected"
            />
          </label>
        </li>
        <li>
          <label>
            <span className="trace-log-tag trace-log-tag--fact">incident</span>
            <input
              value={form.incident_reference}
              onChange={(event) => onUpdate('incident_reference', event.target.value)}
              placeholder="Not detected"
            />
          </label>
        </li>
        <li>
          <label>
            <span className="trace-log-tag trace-log-tag--fact">deployment</span>
            <input
              value={form.deployment_reference}
              onChange={(event) => onUpdate('deployment_reference', event.target.value)}
              placeholder="Not detected"
            />
          </label>
        </li>
        <li>
          <label>
            <span className="trace-log-tag trace-log-tag--fact">pull request</span>
            <input
              inputMode="numeric"
              value={form.pull_request_number}
              onChange={(event) => onUpdate('pull_request_number', event.target.value)}
              placeholder="Not detected"
            />
          </label>
        </li>
      </ul>
      <p className="terminal-note">
        Correct any field if something is wrong, then confirm to actually start
        the investigation — nothing has run yet.
      </p>
      <button className="primary-action" type="submit" disabled={confirmationDisabled}>
        {submitting ? 'Starting investigation…' : 'Confirm & Investigate →'}
      </button>
    </section>
  )
}


export function InvestigationConsolePage({
  onRunStarted,
}: {
  onRunStarted: (runId: string) => void
}) {
  const [form, setForm] = useState(EMPTY_INVESTIGATION_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [extractionError, setExtractionError] = useState<string | null>(null)
  const [extraction, setExtraction] = useState<GroundingExtractionResponse | null>(null)
  const [demoStarting, setDemoStarting] = useState(false)
  const [demoError, setDemoError] = useState<string | null>(null)
  // A description can change while its previous extraction is in flight. A
  // monotonically increasing version prevents that old response from filling
  // the review fields for a newer question.
  const extractionRequestVersion = useRef(0)

  function update(field: keyof typeof EMPTY_INVESTIGATION_FORM, value: string) {
    setError(null)
    if (field !== 'question') {
      setForm((current) => ({ ...current, [field]: value }))
      return
    }

    // Extracted values are proposals for one description, not confirmed
    // context for every later description. Do not feed them into the next
    // extraction as `known_*` fields after the user changes the question.
    extractionRequestVersion.current += 1
    setExtracting(false)
    setExtractionError(null)
    setExtraction(null)
    setForm((current) => ({
      ...current,
      question: value,
      repository_owner: '',
      repository_name: '',
      incident_reference: '',
      deployment_reference: '',
      pull_request_number: '',
    }))
  }

  function selectPreset(value: string) {
    // Resetting to a fresh object preserves normal editing after a preset choice.
    extractionRequestVersion.current += 1
    setExtracting(false)
    setForm(value === 'checkout-500' ? CHECKOUT_500_PRESET : EMPTY_INVESTIGATION_FORM)
    setError(null)
    setExtractionError(null)
    setExtraction(null)
  }

  // Extraction fills the review inputs below; the user can correct each value
  // before the unchanged startInvestigationRun call happens on confirmation.
  async function extractDetails() {
    const description = form.question.trim()
    if (extracting || !description) return
    const requestVersion = extractionRequestVersion.current + 1
    extractionRequestVersion.current = requestVersion
    setExtracting(true)
    setExtractionError(null)
    setExtraction(null)
    try {
      const response = await extractGrounding({
        description,
        known_repository_owner: form.repository_owner.trim() || undefined,
        known_repository_name: form.repository_name.trim() || undefined,
        known_incident_reference: form.incident_reference.trim() || undefined,
        known_deployment_reference: form.deployment_reference.trim() || undefined,
        known_pull_request_number: form.pull_request_number.trim()
          ? Number(form.pull_request_number)
          : undefined,
      })
      if (requestVersion !== extractionRequestVersion.current) return
      setForm((current) => ({
        ...current,
        repository_owner: response.extracted.repository_owner ?? '',
        repository_name: response.extracted.repository_name ?? '',
        incident_reference: response.extracted.incident_reference ?? '',
        deployment_reference: response.extracted.deployment_reference ?? '',
        pull_request_number: response.extracted.pull_request_number === null
          ? ''
          : String(response.extracted.pull_request_number),
      }))
      setExtraction(response)
    } catch (caught) {
      if (requestVersion !== extractionRequestVersion.current) return
      setExtractionError(
        caught instanceof ConnectorApiError
          ? caught.message
          : 'The description could not be analyzed.',
      )
    } finally {
      if (requestVersion === extractionRequestVersion.current) {
        setExtracting(false)
      }
    }
  }

  // Submits the same octo-org/analytics checkout-500 fixture as the "Demo
  // scenario" preset below, but directly, with zero user input, for a public
  // demo deployment where a visitor may not want to fill in the form first.
  async function runDemoScenario() {
    if (demoStarting) return
    const request = buildInvestigationRequest(CHECKOUT_500_PRESET)
    if (typeof request === 'string') {
      setDemoError(request)
      return
    }
    setDemoStarting(true)
    setDemoError(null)
    try {
      const accepted = await startInvestigationRun(request)
      onRunStarted(accepted.run_id)
    } catch (caught) {
      setDemoError(
        caught instanceof ConnectorApiError
          ? caught.message
          : 'The demo investigation could not be started.',
      )
    } finally {
      setDemoStarting(false)
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    if (!extraction) {
      setError('Extract the details and review them before starting an investigation.')
      return
    }
    const request = buildInvestigationRequest(form)
    if (typeof request === 'string') {
      setError(request)
      return
    }
    setSubmitting(true)
    try {
      const accepted = await startInvestigationRun(request)
      onRunStarted(accepted.run_id)
    } catch (caught) {
      setError(
        caught instanceof ConnectorApiError
          ? caught.message
          : 'The investigation request could not be submitted.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="Whyline home">
          <span className="brand-mark" aria-hidden="true">W</span>
          <span>Whyline</span>
        </a>
        <span className="environment-badge">Investigation console</span>
      </header>
      <section className="workspace" aria-labelledby="investigation-title">
        <div className="investigation-console-heading">
          <p className="eyebrow">NEW INVESTIGATION</p>
          <h1 id="investigation-title">What happened?</h1>
          <div className="demo-launch">
            <button
              className="secondary-action"
              type="button"
              onClick={runDemoScenario}
              disabled={demoStarting}
            >
              {demoStarting ? 'Starting demo investigation…' : 'Run demo investigation'}
            </button>
            <p className="inline-hint">
              Runs the checkout-500 example investigation immediately, no
              form-filling required. First request may take up to a minute if
              the server has been idle.
            </p>
            <a className="workspace-signup-link" href="/signup">
              Have your own repo? Sign up to connect your real accounts →
            </a>
            {demoError && <p className="inline-alert" role="alert">{demoError}</p>}
          </div>
        </div>
        <form className="investigation-form" onSubmit={submit}>
          <label className="investigation-question">
            <span>What do you want to investigate?</span>
            <textarea
              value={form.question}
              onChange={(event) => update('question', event.target.value)}
              placeholder="Why did checkout start returning 500s after the latest deployment?"
              rows={5}
              aria-invalid={error?.includes('What do you want') || undefined}
            />
          </label>
          <div className="grounding-extraction">
            <button
              className="secondary-action"
              type="button"
              onClick={extractDetails}
              disabled={extracting || !form.question.trim()}
            >
              {extracting
                ? 'Reading description…'
                : 'Fill in repository, incident, deployment, PR from description'}
            </button>
            {extractionError && (
              <p className="inline-alert" role="alert">{extractionError}</p>
            )}
          </div>
          <label className="demo-scenario">
            <span>Demo scenario</span>
            <select onChange={(event) => selectPreset(event.target.value)} defaultValue="custom">
              <option value="custom">Custom investigation</option>
              <option value="checkout-500">Checkout 500 after deployment</option>
            </select>
          </label>
          {extraction && (
            <GroundingExtractionReview
              extraction={extraction}
              form={form}
              submitting={submitting}
              onUpdate={update}
            />
          )}
          {error && <p className="inline-alert" role="alert">{error}</p>}
        </form>
      </section>
    </main>
  )
}
