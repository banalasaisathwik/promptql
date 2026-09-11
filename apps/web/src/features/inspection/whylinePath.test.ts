import { expect, test } from 'bun:test'
import { normalizedSlashPath, repositoryRelativePath } from './whylinePath'

test('normalizedSlashPath converts backslashes and strips a leading ./', () => {
  expect(normalizedSlashPath('.\\app\\checkout.py')).toBe('app/checkout.py')
  expect(normalizedSlashPath('./app/checkout.py')).toBe('app/checkout.py')
  expect(normalizedSlashPath('app/checkout.py')).toBe('app/checkout.py')
})

test('repositoryRelativePath strips the infrastructure prefix in front of the repository root', () => {
  expect(
    repositoryRelativePath('/opt/render/project/src/sandbox-target/app/checkout.py', 'sandbox-target'),
  ).toBe('app/checkout.py')
})

test('repositoryRelativePath leaves an already relative path unchanged', () => {
  expect(repositoryRelativePath('app/checkout.py', 'sandbox-target')).toBe('app/checkout.py')
})

test('repositoryRelativePath normalizes Windows separators before matching the root', () => {
  expect(
    repositoryRelativePath('C:\\builds\\sandbox-target\\app\\checkout.py', 'sandbox-target'),
  ).toBe('app/checkout.py')
})

test('repositoryRelativePath returns the normalized path unchanged when no repository name is known', () => {
  expect(repositoryRelativePath('/opt/render/project/src/sandbox-target/app/checkout.py')).toBe(
    '/opt/render/project/src/sandbox-target/app/checkout.py',
  )
})

test('repositoryRelativePath returns the normalized path unchanged when the root name is not present', () => {
  expect(repositoryRelativePath('/opt/render/project/src/other-repo/app/checkout.py', 'sandbox-target')).toBe(
    '/opt/render/project/src/other-repo/app/checkout.py',
  )
})

test('repositoryRelativePath returns the normalized path unchanged when the root name is the last segment', () => {
  expect(repositoryRelativePath('/opt/render/project/src/sandbox-target', 'sandbox-target')).toBe(
    '/opt/render/project/src/sandbox-target',
  )
})

test('repositoryRelativePath matches the last occurrence when the repository name repeats in the path', () => {
  expect(
    repositoryRelativePath('/opt/sandbox-target/checkouts/sandbox-target/app/checkout.py', 'sandbox-target'),
  ).toBe('app/checkout.py')
})
