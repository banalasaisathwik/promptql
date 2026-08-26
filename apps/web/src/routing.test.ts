import { expect, test } from 'bun:test'
import { runPathFor, runTracePathFor } from './routing'


test('builds the dedicated persisted run route from the accepted run ID', () => {
  expect(runPathFor('49a8a46d-5c69-4e5d-a928-6a149b84d6e7')).toBe(
    '/runs/49a8a46d-5c69-4e5d-a928-6a149b84d6e7',
  )
})


test('builds the live trace route from the accepted run ID', () => {
  expect(runTracePathFor('49a8a46d-5c69-4e5d-a928-6a149b84d6e7')).toBe(
    '/runs/49a8a46d-5c69-4e5d-a928-6a149b84d6e7/trace',
  )
})
