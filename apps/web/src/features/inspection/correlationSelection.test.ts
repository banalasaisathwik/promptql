import { expect, test } from 'bun:test'
import { canAnalyzeRepositoryScan, correlationRequestForSelection } from './correlationSelection'

test('a scan request is derived exclusively from discovered repository and project records', () => {
  const request = correlationRequestForSelection(
    {
      owner: 'banalasaisathwik', name: 'promptql-sandbox',
      full_name: 'banalasaisathwik/promptql-sandbox', private: false, default_branch: 'main',
    },
    { organization_slug: 'student-whe', project_slug: 'python-fastapi', name: 'python-fastapi' },
  )

  expect(request).toEqual({
    repository_owner: 'banalasaisathwik',
    repository_name: 'promptql-sandbox',
    sentry_project_slug: 'python-fastapi',
  })
  expect(request?.sentry_project_slug).not.toBe('PYTHON-FASTAPI-1')
  expect(correlationRequestForSelection(undefined, undefined)).toBeNull()
})

test('Analyze remains disabled until connected discovery records are selected', () => {
  const repository = { owner: 'octo', name: 'api', full_name: 'octo/api', private: false, default_branch: 'main' }
  const project = { organization_slug: 'acme', project_slug: 'api', name: 'API' }

  expect(canAnalyzeRepositoryScan(false, true, repository, project, false)).toBe(false)
  expect(canAnalyzeRepositoryScan(true, false, repository, project, false)).toBe(false)
  expect(canAnalyzeRepositoryScan(true, true, null, project, false)).toBe(false)
  expect(canAnalyzeRepositoryScan(true, true, repository, null, false)).toBe(false)
  expect(canAnalyzeRepositoryScan(true, true, repository, project, true)).toBe(false)
  expect(canAnalyzeRepositoryScan(true, true, repository, project, false)).toBe(true)
})
