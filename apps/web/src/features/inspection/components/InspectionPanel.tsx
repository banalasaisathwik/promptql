/** Present loading, empty, and successful connector-inspection states. */

import type { GitHubUser, PullRequestInspection } from '../types'


interface InspectionPanelProps {
  inspection: PullRequestInspection | null
  loading: boolean
}


function userList(users: GitHubUser[]): string {
  // Joining in one helper keeps the empty-state wording consistent for
  // assignees and requested reviewers.
  return users.length > 0 ? users.map((user) => user.login).join(', ') : 'None'
}


function InspectionResult({ inspection }: { inspection: PullRequestInspection }) {
  // Destructuring gives short local names while preserving the combined
  // inspection object for the raw JSON view at the bottom.
  const { github, jira } = inspection

  return (
    <div className="inspection-result">
      <div className="ready-state">
        <span className="ready-icon" aria-hidden="true">✓</span>
        <div>
          <strong>Inspection received</strong>
          <p>GitHub and Jira fixtures returned by the backend.</p>
        </div>
      </div>

      <section className="provider-section" aria-labelledby="github-heading">
        <div className="provider-heading">
          <h3 id="github-heading">GitHub</h3>
          <span className="provider-key">#{inspection.request.pr_number}</span>
        </div>

        {/* A description list (<dl>) represents label/value facts more
            accurately than unrelated paragraphs or a layout-only table. */}
        <dl className="fact-grid">
          <div><dt>State</dt><dd>{github.state}</dd></div>
          <div><dt>Draft</dt><dd>{github.is_draft ? 'Yes' : 'No'}</dd></div>
          <div><dt>Mergeability</dt><dd>{github.mergeability}</dd></div>
          <div><dt>Approvals</dt><dd>{github.approvals.length}</dd></div>
          <div>
            <dt>Changes requested</dt>
            <dd>{github.changes_requested ? 'Yes' : 'No'}</dd>
          </div>
          <div><dt>Author</dt><dd>{github.author.login}</dd></div>
        </dl>

        <div className="evidence-group">
          <p className="evidence-label">Required CI checks</p>
          <ul className="check-list">
            {github.required_checks.map((check) => (
              <li key={check.name}>
                <span>{check.name}</span>
                <span className={`check-status check-status--${check.status}`}>
                  {check.status}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <dl className="people-list">
          <div><dt>Assignees</dt><dd>{userList(github.assignees)}</dd></div>
          <div>
            <dt>Requested reviewers</dt>
            <dd>{userList(github.requested_reviewers)}</dd>
          </div>
        </dl>
      </section>

      <section className="provider-section" aria-labelledby="jira-heading">
        <div className="provider-heading">
          <h3 id="jira-heading">Jira</h3>
          <span className="provider-key">{jira.issue_key}</span>
        </div>
        <dl className="fact-grid fact-grid--jira">
          <div><dt>Status</dt><dd>{jira.status.replace('_', ' ')}</dd></div>
          <div>
            <dt>Blocker</dt>
            <dd>{jira.blocker_state.replace('_', ' ')}</dd>
          </div>
          <div>
            <dt>Assignee</dt>
            <dd>{jira.assignee?.display_name ?? 'Unassigned'}</dd>
          </div>
        </dl>
      </section>

      {/* <details> keeps complete debugging evidence available without making
          the primary view overwhelming for a new user. */}
      <details className="raw-response">
        <summary>View raw response</summary>
        <pre>{JSON.stringify(inspection, null, 2)}</pre>
      </details>
    </div>
  )
}


export function InspectionPanel({ inspection, loading }: InspectionPanelProps) {
  return (
    <aside className="preview-card" aria-live="polite" aria-busy={loading}>
      <div className="preview-heading">
        <div>
          <p className="step-label">Backend evidence</p>
          <h2>Inspection response</h2>
        </div>
        <span
          className={`status-dot ${inspection ? 'status-dot--ready' : ''}`}
          aria-hidden="true"
        />
      </div>

      {loading ? (
        <div className="empty-state">
          <div className="spinner" aria-hidden="true" />
          <h3>Loading inspection</h3>
        </div>
      ) : inspection ? (
        <InspectionResult inspection={inspection} />
      ) : (
        <div className="empty-state">
          <div className="empty-symbol" aria-hidden="true">{'{ }'}</div>
          <h3>Your response will appear here</h3>
          <p>Select a fixture and prepare the request to call the backend.</p>
        </div>
      )}
    </aside>
  )
}
