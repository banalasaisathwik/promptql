import { expect, test } from 'bun:test'
import { ConnectorApiError } from './apiError'
import { whylineAnalysisLabel, whylineCategoryLabel, whylineDiscoveryErrorMessage, whylineErrorMessage, whylineGroundingLabel, whylineScanErrorMessage } from './whylinePresentation'

test('maps scan errors without overwriting auth and credential error messages', () => {
  expect(whylineErrorMessage(new ConnectorApiError('An account with this email already exists.', 409))).toBe('An account with this email already exists.')
  expect(whylineScanErrorMessage(new ConnectorApiError('raw', 409))).toBe('Required source is not connected.')
  expect(whylineScanErrorMessage(new ConnectorApiError('raw', 422))).toBe('Check the entered values.')
  expect(whylineScanErrorMessage(new ConnectorApiError('raw', 503))).toBe('A connected provider is temporarily unavailable.')
  expect(whylineDiscoveryErrorMessage('GitHub', new ConnectorApiError('raw', 503))).toBe('GitHub is temporarily unavailable. Try again.')
  expect(whylineDiscoveryErrorMessage('Sentry', new ConnectorApiError('raw', 409))).toBe('Connect Sentry to choose a project.')
})

test('preserves the backend analysis distinction in user-facing labels', () => {
  expect(whylineAnalysisLabel('completed')).toBe('Grounded')
  expect(whylineAnalysisLabel('insufficient_evidence')).toBe('Insufficient evidence')
  expect(whylineAnalysisLabel('no_validated_hypothesis')).toBe('No grounded hypothesis')
  expect(whylineAnalysisLabel('code_finding_unavailable')).toContain('code location unavailable')
})

test('renders validated taxonomy and deterministic grounding as readable labels', () => {
  expect(whylineCategoryLabel('error_handling_or_null_path')).toBe('Error handling / invalid state')
  expect(whylineGroundingLabel('strong')).toBe('Strong grounding')
  expect(whylineGroundingLabel('insufficient')).toBe('Insufficient evidence')
})
