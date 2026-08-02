/**
 * State coordinator for the connector-inspection page.
 *
 * Components render UI, API modules perform HTTP work, validators protect data,
 * and this page coordinates state transitions between those responsibilities.
 */

import { useEffect, useState } from 'react'
import { fetchFixtureScenarios, inspectPullRequest } from './api'
import { ConnectorApiError } from './apiError'
import { InspectionPanel } from './components/InspectionPanel'
import { RequestForm } from './components/RequestForm'
import {
  createConnectorRequest,
  EMPTY_CONNECTOR_REQUEST_DRAFT,
} from './requestValidation'
import type {
  ConnectorRequestDraft,
  ConnectorRequestErrors,
  FixtureScenario,
  PullRequestInspection,
} from './types'


export function ConnectorInspectionPage() {
  // Each useState call owns one independent piece of changing UI data. Keeping
  // request, catalog, and submission state separate makes transitions explicit.
  const [draft, setDraft] = useState<ConnectorRequestDraft>(
    EMPTY_CONNECTOR_REQUEST_DRAFT,
  )
  const [errors, setErrors] = useState<ConnectorRequestErrors>({})
  const [scenarios, setScenarios] = useState<FixtureScenario[]>([])
  const [selectedScenarioId, setSelectedScenarioId] = useState('')
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [inspection, setInspection] = useState<PullRequestInspection | null>(null)
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    // Effects perform work outside rendering. AbortController prevents an
    // in-flight fetch from updating state after this page has been unmounted.
    const controller = new AbortController()

    async function loadScenarios() {
      try {
        const loadedScenarios = await fetchFixtureScenarios(controller.signal)
        setScenarios(loadedScenarios)
      } catch (error) {
        if (!controller.signal.aborted) {
          setCatalogError(
            error instanceof ConnectorApiError
              ? error.message
              : 'Could not load connector scenarios.',
          )
        }
      } finally {
        if (!controller.signal.aborted) {
          setCatalogLoading(false)
        }
      }
    }

    void loadScenarios()

    // React calls this cleanup function when the component leaves the page.
    return () => controller.abort()
  }, [])

  function clearInspectionResult() {
    setInspection(null)
    setSubmissionError(null)
  }

  function updateDraft(field: keyof ConnectorRequestDraft, value: string) {
    // The spread operator copies existing fields before replacing one field;
    // React state should be replaced rather than mutated in place.
    setDraft((currentDraft) => ({ ...currentDraft, [field]: value }))
    setErrors((currentErrors) => ({ ...currentErrors, [field]: undefined }))
    setSelectedScenarioId('')
    clearInspectionResult()
  }

  function selectScenario(scenarioId: string) {
    setSelectedScenarioId(scenarioId)
    setErrors({})
    clearInspectionResult()

    const scenario = scenarios.find((item) => item.id === scenarioId)
    if (!scenario) {
      setDraft(EMPTY_CONNECTOR_REQUEST_DRAFT)
      return
    }

    // Form controls need strings, so the validated numeric PR is converted only
    // for editing and converted back during submit validation.
    setDraft({
      repository_owner: scenario.request.repository_owner,
      repository_name: scenario.request.repository_name,
      pr_number: String(scenario.request.pr_number),
    })
  }

  async function submitInspection() {
    const result = createConnectorRequest(draft)

    if (!result.ok) {
      setErrors(result.errors)
      clearInspectionResult()
      return
    }

    setErrors({})
    setSubmitting(true)
    clearInspectionResult()

    try {
      const response = await inspectPullRequest(result.request)
      setInspection(response)
    } catch (error) {
      setSubmissionError(
        error instanceof ConnectorApiError
          ? error.message
          : 'The inspection request failed unexpectedly.',
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
        <span className="environment-badge">Connector sandbox</span>
      </header>

      <section className="workspace" aria-labelledby="page-title">
        <div className="intro">
          <p className="eyebrow">GitHub + Jira</p>
          <h1 id="page-title">Inspect a pull request</h1>
          <p className="intro-copy">
            Choose a backend fixture or enter a repository reference, then load
            its GitHub and Jira evidence through the versioned API.
          </p>
        </div>

        <div className="content-grid">
          <RequestForm
            draft={draft}
            errors={errors}
            scenarios={scenarios}
            selectedScenarioId={selectedScenarioId}
            catalogLoading={catalogLoading}
            catalogError={catalogError}
            submitting={submitting}
            submissionError={submissionError}
            onDraftChange={updateDraft}
            onScenarioChange={selectScenario}
            onSubmit={submitInspection}
          />
          <InspectionPanel inspection={inspection} loading={submitting} />
        </div>
      </section>

      <footer className="site-footer">
        <span>V1 connector inspection</span>
        <span>Backend fixture environment</span>
      </footer>
    </main>
  )
}
