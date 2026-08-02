/** Controlled form that collects a connector request from the user. */

import type { FormEvent } from 'react'
import type {
  ConnectorRequestDraft,
  ConnectorRequestErrors,
  FixtureScenario,
} from '../types'


interface RequestFormProps {
  draft: ConnectorRequestDraft
  errors: ConnectorRequestErrors
  scenarios: FixtureScenario[]
  selectedScenarioId: string
  catalogLoading: boolean
  catalogError: string | null
  submitting: boolean
  submissionError: string | null
  onDraftChange: (field: keyof ConnectorRequestDraft, value: string) => void
  onScenarioChange: (scenarioId: string) => void
  onSubmit: () => Promise<void>
}


export function RequestForm({
  draft,
  errors,
  scenarios,
  selectedScenarioId,
  catalogLoading,
  catalogError,
  submitting,
  submissionError,
  onDraftChange,
  onScenarioChange,
  onSubmit,
}: RequestFormProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    // Browser forms normally reload the page. React keeps the flow client-side,
    // so preventDefault stops that navigation before calling the async handler.
    event.preventDefault()
    void onSubmit()
  }

  return (
    <form className="request-card" onSubmit={handleSubmit} noValidate>
      <div className="card-heading">
        <div>
          <p className="step-label">Request details</p>
          <h2>Repository reference</h2>
        </div>
        <span className="step-number" aria-hidden="true">01</span>
      </div>

      {/* The dropdown is backend-owned. Manual fields remain editable so an
          unknown request can exercise the typed 404 behavior as well. */}
      <div className="field-group field-group--scenario">
        <label htmlFor="fixture-scenario">Backend fixture</label>
        <select
          id="fixture-scenario"
          value={selectedScenarioId}
          onChange={(event) => onScenarioChange(event.target.value)}
          disabled={catalogLoading}
        >
          <option value="">
            {catalogLoading ? 'Loading fixtures…' : 'Custom request'}
          </option>
          {scenarios.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {scenario.label} — {scenario.request.repository_owner}/
              {scenario.request.repository_name}#{scenario.request.pr_number}
            </option>
          ))}
        </select>
        <p className="field-hint">
          Options are loaded from the backend fixture catalog.
        </p>
        {catalogError && <p className="inline-alert">{catalogError}</p>}
      </div>

      <div className="field-grid">
        <div className="field-group">
          <label htmlFor="repository-owner">Repository owner</label>
          <input
            id="repository-owner"
            name="repository_owner"
            type="text"
            value={draft.repository_owner}
            onChange={(event) =>
              onDraftChange('repository_owner', event.target.value)
            }
            placeholder="acme"
            aria-invalid={Boolean(errors.repository_owner)}
            aria-describedby="repository-owner-message"
          />
          <p
            className={errors.repository_owner ? 'field-error' : 'field-hint'}
            id="repository-owner-message"
          >
            {errors.repository_owner ?? 'GitHub user or organization'}
          </p>
        </div>

        <div className="field-group">
          <label htmlFor="repository-name">Repository name</label>
          <input
            id="repository-name"
            name="repository_name"
            type="text"
            value={draft.repository_name}
            onChange={(event) =>
              onDraftChange('repository_name', event.target.value)
            }
            placeholder="analytics"
            aria-invalid={Boolean(errors.repository_name)}
            aria-describedby="repository-name-message"
          />
          <p
            className={errors.repository_name ? 'field-error' : 'field-hint'}
            id="repository-name-message"
          >
            {errors.repository_name ?? 'Exact repository slug'}
          </p>
        </div>

        <div className="field-group field-group--full">
          <label htmlFor="pr-number">Pull request number</label>
          <div className="number-input">
            <span aria-hidden="true">#</span>
            <input
              id="pr-number"
              name="pr_number"
              type="text"
              inputMode="numeric"
              value={draft.pr_number}
              onChange={(event) => onDraftChange('pr_number', event.target.value)}
              placeholder="123"
              aria-invalid={Boolean(errors.pr_number)}
              aria-describedby="pr-number-message"
            />
          </div>
          <p
            className={errors.pr_number ? 'field-error' : 'field-hint'}
            id="pr-number-message"
          >
            {errors.pr_number ??
              'Positive whole number from the pull request URL'}
          </p>
        </div>
      </div>

      <button className="primary-button" type="submit" disabled={submitting}>
        {submitting ? 'Inspecting…' : 'Prepare request'}
        {!submitting && <span aria-hidden="true">→</span>}
      </button>

      {/* role="alert" asks screen readers to announce an asynchronous failure. */}
      {submissionError && (
        <p className="submission-error" role="alert">
          {submissionError}
        </p>
      )}
    </form>
  )
}
