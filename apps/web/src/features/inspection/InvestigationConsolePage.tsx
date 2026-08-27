import { useState } from 'react'
import type { FormEvent } from 'react'
import { extractGrounding, startInvestigationRun } from './api'
import { ConnectorApiError } from './apiError'
import {
  buildInvestigationRequest,
  CHECKOUT_500_PRESET,
  EMPTY_INVESTIGATION_FORM,
} from './investigationRequest'


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
  const [clarificationQuestion, setClarificationQuestion] = useState<string | null>(null)
  const [contextOpen, setContextOpen] = useState(false)

  function update(field: keyof typeof EMPTY_INVESTIGATION_FORM, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
    setError(null)
  }

  function selectPreset(value: string) {
    // Resetting to a fresh object preserves normal editing after a preset choice.
    setForm(value === 'checkout-500' ? CHECKOUT_500_PRESET : EMPTY_INVESTIGATION_FORM)
    setError(null)
    setExtractionError(null)
    setClarificationQuestion(null)
  }

  // This only fills the structured fields below for the user to review and
  // edit; it never starts an investigation. Submitting still goes through the
  // unchanged startInvestigationRun call below, on the user's explicit click.
  async function extractDetails() {
    if (extracting || !form.question.trim()) return
    setExtracting(true)
    setExtractionError(null)
    try {
      const response = await extractGrounding({
        description: form.question,
        known_repository_owner: form.repository_owner.trim() || undefined,
        known_repository_name: form.repository_name.trim() || undefined,
        known_incident_reference: form.incident_reference.trim() || undefined,
        known_deployment_reference: form.deployment_reference.trim() || undefined,
        known_pull_request_number: form.pull_request_number.trim()
          ? Number(form.pull_request_number)
          : undefined,
      })
      setForm((current) => ({
        ...current,
        repository_owner: response.extracted.repository_owner ?? current.repository_owner,
        repository_name: response.extracted.repository_name ?? current.repository_name,
        incident_reference:
          response.extracted.incident_reference ?? current.incident_reference,
        deployment_reference:
          response.extracted.deployment_reference ?? current.deployment_reference,
        pull_request_number:
          response.extracted.pull_request_number !== null
            ? String(response.extracted.pull_request_number)
            : current.pull_request_number,
      }))
      setClarificationQuestion(
        response.status === 'needs_clarification' ? response.question : null,
      )
      setContextOpen(true)
    } catch (caught) {
      setExtractionError(
        caught instanceof ConnectorApiError
          ? caught.message
          : 'The description could not be analyzed.',
      )
    } finally {
      setExtracting(false)
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
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
        <a className="brand" href="/" aria-label="PromptQL home">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span>PromptQL</span>
        </a>
        <span className="environment-badge">Investigation console</span>
      </header>
      <section className="workspace" aria-labelledby="investigation-title">
        <div className="intro">
          <p className="eyebrow">Grounded investigation</p>
          <h1 id="investigation-title">Investigate an engineering issue</h1>
          <p className="intro-copy">
            Ask about an incident, deployment, or code change. PromptQL uses
            your question as the investigation goal and grounds results in validated Facts.
          </p>
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
            {clarificationQuestion && (
              <p className="inline-hint" role="status">{clarificationQuestion}</p>
            )}
          </div>
          <button className="primary-action" type="submit" disabled={submitting}>
            {submitting ? 'Starting investigation…' : 'Investigate →'}
          </button>
          <label className="demo-scenario">
            <span>Demo scenario</span>
            <select onChange={(event) => selectPreset(event.target.value)} defaultValue="custom">
              <option value="custom">Custom investigation</option>
              <option value="checkout-500">Checkout 500 after deployment</option>
            </select>
          </label>
          <details
            className="investigation-context"
            open={contextOpen}
            onToggle={(event) => setContextOpen(event.currentTarget.open)}
          >
            <summary>Optional investigation context <small>Repository details are required for GitHub evidence.</small></summary>
            <div className="form-grid">
              <label>Repository owner<input value={form.repository_owner} onChange={(event) => update('repository_owner', event.target.value)} /></label>
              <label>Repository name<input value={form.repository_name} onChange={(event) => update('repository_name', event.target.value)} /></label>
              <label>Incident ID<input value={form.incident_reference} onChange={(event) => update('incident_reference', event.target.value)} placeholder="incident:checkout-500" /></label>
              <label>Service<input value={form.service} onChange={(event) => update('service', event.target.value)} /></label>
              <label>Environment<input value={form.environment} onChange={(event) => update('environment', event.target.value)} placeholder="production" /></label>
              <label>Deployment ID<input value={form.deployment_reference} onChange={(event) => update('deployment_reference', event.target.value)} /></label>
              <label>Pull request number<input inputMode="numeric" value={form.pull_request_number} onChange={(event) => update('pull_request_number', event.target.value)} /></label>
            </div>
          </details>
          {error && <p className="inline-alert" role="alert">{error}</p>}
        </form>
      </section>
    </main>
  )
}
