import { expect, test } from 'bun:test'
import { computeLineDiff } from './whylineDiff'

test('computeLineDiff marks a single changed line as removed then added', () => {
  const diff = computeLineDiff('STOCK[item_id - 1] -= qty', 'STOCK[item_id] -= qty')
  expect(diff).toEqual([
    { kind: 'removed', text: 'STOCK[item_id - 1] -= qty' },
    { kind: 'added', text: 'STOCK[item_id] -= qty' },
  ])
})

test('computeLineDiff keeps unchanged surrounding lines as context', () => {
  const oldText = 'def f():\n    old_line()\n    return True'
  const newText = 'def f():\n    new_line()\n    return True'
  const diff = computeLineDiff(oldText, newText)
  expect(diff).toEqual([
    { kind: 'context', text: 'def f():' },
    { kind: 'removed', text: '    old_line()' },
    { kind: 'added', text: '    new_line()' },
    { kind: 'context', text: '    return True' },
  ])
})

test('computeLineDiff produces no changed lines for identical text', () => {
  const diff = computeLineDiff('a\nb\nc', 'a\nb\nc')
  expect(diff.every((line) => line.kind === 'context')).toBe(true)
})

test('computeLineDiff handles a pure addition', () => {
  const diff = computeLineDiff('a', 'a\nb')
  expect(diff).toEqual([
    { kind: 'context', text: 'a' },
    { kind: 'added', text: 'b' },
  ])
})

test('computeLineDiff handles a pure removal', () => {
  const diff = computeLineDiff('a\nb', 'a')
  expect(diff).toEqual([
    { kind: 'context', text: 'a' },
    { kind: 'removed', text: 'b' },
  ])
})
