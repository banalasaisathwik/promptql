import { expect, test } from 'bun:test'
import { filterDiscoveryItems } from './discoverySearch'

test('filters repository discovery by owner or repository name without changing records', () => {
  const repositories = [
    { owner: 'banalasaisathwik', name: 'promptql-sandbox' },
    { owner: 'octo-org', name: 'gateway' },
  ]

  expect(filterDiscoveryItems(repositories, 'SATHWIK', (item) => `${item.owner} ${item.name}`))
    .toEqual([repositories[0]])
  expect(filterDiscoveryItems(repositories, 'gateway', (item) => `${item.owner} ${item.name}`))
    .toEqual([repositories[1]])
})

test('filters Sentry projects client-side by organization, slug, or display name', () => {
  const projects = [
    { organization_slug: 'student-whe', project_slug: 'python-fastapi', name: 'Python API' },
    { organization_slug: 'student-whe', project_slug: 'python-flask', name: 'Flask API' },
  ]

  expect(filterDiscoveryItems(projects, 'flask', (item) => `${item.organization_slug} ${item.project_slug} ${item.name}`))
    .toEqual([projects[1]])
})
