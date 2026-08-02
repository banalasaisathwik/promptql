/** Convert editable form strings into a validated backend request. */

import type {
  ConnectorRequestDraft,
  ConnectorRequestErrors,
  ConnectorRequestResult,
} from './types'


// A shared initial object avoids repeating the three empty values in components.
// Components never mutate this object; React state updates create new objects.
export const EMPTY_CONNECTOR_REQUEST_DRAFT: ConnectorRequestDraft = {
  repository_owner: '',
  repository_name: '',
  pr_number: '',
}


export function createConnectorRequest(
  draft: ConnectorRequestDraft,
): ConnectorRequestResult {
  // Repository text is normalized before validation so accidental surrounding
  // spaces do not become part of the backend lookup key.
  const repositoryOwner = draft.repository_owner.trim()
  const repositoryName = draft.repository_name.trim()
  const errors: ConnectorRequestErrors = {}

  if (!repositoryOwner) {
    errors.repository_owner = 'Enter a repository owner.'
  }

  if (!repositoryName) {
    errors.repository_name = 'Enter a repository name.'
  }

  // Number() accepts surprising strings such as "1e3" and whitespace. The
  // regular expression permits only the positive base-10 integer syntax the UI
  // promises. Safe-integer validation prevents silent JSON precision loss.
  const isPositiveIntegerText = /^[1-9]\d*$/.test(draft.pr_number)
  const prNumber = isPositiveIntegerText ? Number(draft.pr_number) : Number.NaN

  if (!isPositiveIntegerText || !Number.isSafeInteger(prNumber)) {
    errors.pr_number = 'Enter a positive whole number.'
  }

  // This check chooses one branch of the discriminated union returned below.
  // Callers can inspect `result.ok` and TypeScript then knows which fields exist.
  if (Object.keys(errors).length > 0) {
    return { ok: false, errors }
  }

  return {
    ok: true,
    request: {
      repository_owner: repositoryOwner,
      repository_name: repositoryName,
      pr_number: prNumber,
    },
  }
}
