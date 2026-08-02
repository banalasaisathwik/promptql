import { expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { RequestForm } from './RequestForm'


test('disables submission while a request is loading', () => {
  const markup = renderToStaticMarkup(
    <RequestForm
      draft={{ repository_owner: 'acme', repository_name: 'analytics', pr_number: '1' }}
      errors={{}}
      scenarios={[]}
      selectedScenarioId=""
      catalogLoading={false}
      catalogError={null}
      submitting={true}
      submissionError={null}
      onDraftChange={() => undefined}
      onScenarioChange={() => undefined}
      onSubmit={async () => undefined}
    />,
  )

  expect(markup).toContain('disabled=""')
  expect(markup).toContain('Analysing…')
})
