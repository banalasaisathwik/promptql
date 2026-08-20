import { useState } from 'react'
import type { FormEvent } from 'react'
import { startInvestigationRun } from './api'
import { ConnectorApiError } from './apiError'
import {
  buildInvestigationRequest,
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

  function update(field: keyof typeof EMPTY_INVESTIGATION_FORM, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
    setError(null)
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
          <h1 id="investigation-title">Investigate an incident</h1>
          <p className="intro-copy">
            Submit structured context, watch the live execution snapshot, and
            review a conclusion grounded in validated Facts.
          </p>
        </div>
        <form className="investigation-form" onSubmit={submit}>
          <div className="form-grid">
            <label>Repository owner<input value={form.repository_owner} onChange={(event) => update('repository_owner', event.target.value)} /></label>
            <label>Repository name<input value={form.repository_name} onChange={(event) => update('repository_name', event.target.value)} /></label>
            <label>Incident ID<input value={form.incident_reference} onChange={(event) => update('incident_reference', event.target.value)} placeholder="incident:checkout-500" /></label>
            <label>Service<input value={form.service} onChange={(event) => update('service', event.target.value)} /></label>
            <label>Environment<input value={form.environment} onChange={(event) => update('environment', event.target.value)} placeholder="production" /></label>
            <label>Deployment ID<input value={form.deployment_reference} onChange={(event) => update('deployment_reference', event.target.value)} /></label>
            <label>Pull request number<input inputMode="numeric" value={form.pull_request_number} onChange={(event) => update('pull_request_number', event.target.value)} /></label>
          </div>
          <label>Incident summary<textarea value={form.incident_summary} onChange={(event) => update('incident_summary', event.target.value)} rows={4} /></label>
          {error && <p className="inline-alert" role="alert">{error}</p>}
          <button className="primary-action" type="submit" disabled={submitting}>
            {submitting ? 'Starting investigation…' : 'Investigate'}
          </button>
        </form>
      </section>
    </main>
  )
}
