import { useEffect, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import {
  connectCredential, disconnectCredential, fetchCredentialConnections, fetchGitHubContext,
  fetchSentryProjects, loginWorkspace, logoutWorkspace, registerWorkspace, runCorrelationScan,
} from './api'
import type {
  AuthenticatedUser, CorrelationIssue, CorrelationScanResult, CredentialConnections,
  CredentialProvider, GitHubContext, GitHubRepository, SentryProject,
} from './api'
import { canAnalyzeRepositoryScan, correlationRequestForSelection } from './correlationSelection'
import { computeLineDiff } from './whylineDiff'
import { filterDiscoveryItems } from './discoverySearch'
import { repositoryRelativePath } from './whylinePath'
import {
  groupCodeFindings, whylineAnalysisLabel as analysisLabel, whylineCategoryLabel as categoryLabel,
  whylineDiscoveryErrorMessage as discoveryErrorMessage, whylineErrorMessage as errorMessage,
  whylineFailureSummary as failureSummary, whylineGroundingLabel as groundingLabel,
  whylineLocationParts as locationParts, whylineScanErrorMessage as scanErrorMessage,
} from './whylinePresentation'
import type { WhylineCodeFindingGroup } from './whylinePresentation'
import './whyline.css'

const providers: Array<{ id: CredentialProvider, name: string, required: boolean }> = [
  { id: 'github', name: 'GitHub', required: true },
  { id: 'sentry', name: 'Sentry', required: true },
  { id: 'jira', name: 'Jira', required: false },
]

type ComboboxProps<T> = {
  id: string
  label: string
  searchLabel: string
  emptyLabel: string
  loadingLabel: string
  providerMark: string
  items: readonly T[]
  selected: T | null
  disabled: boolean
  loading: boolean
  getKey: (item: T) => string
  getLabel: (item: T) => string
  getSearchText: (item: T) => string
  getMeta?: (item: T) => string | null
  onSelect: (item: T) => void
}

function DiscoveryCombobox<T>({
  id, label, searchLabel, emptyLabel, loadingLabel, providerMark, items, selected, disabled,
  loading, getKey, getLabel, getSearchText, getMeta, onSelect,
}: ComboboxProps<T>) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const visibleItems = filterDiscoveryItems(items, query, getSearchText)
  const listId = `${id}-listbox`
  const selectedLabel = selected ? getLabel(selected) : loading ? loadingLabel : `Select ${label.toLowerCase()}`

  function choose(item: T) {
    onSelect(item)
    setQuery('')
    setActiveIndex(0)
    setOpen(false)
  }

  function moveActive(delta: number) {
    if (!visibleItems.length) return
    setActiveIndex((current) => (current + delta + visibleItems.length) % visibleItems.length)
  }

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return
    if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setOpen(true)
      setActiveIndex(0)
    }
  }

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') { event.preventDefault(); moveActive(1) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); moveActive(-1) }
    else if (event.key === 'Enter') {
      event.preventDefault()
      const item = visibleItems[activeIndex]
      if (item) choose(item)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setOpen(false)
      setQuery('')
    }
  }

  return <div className="wl-combobox">
    <span id={`${id}-label`} className="wl-field-label">{label}</span>
    <button type="button" className="wl-combobox-trigger" aria-labelledby={`${id}-label ${id}-value`} aria-expanded={open} aria-controls={open ? listId : undefined} disabled={disabled} onClick={() => { setOpen((current) => !current); setActiveIndex(0) }} onKeyDown={onTriggerKeyDown}>
      <span className="wl-combobox-provider" aria-hidden="true">{providerMark}</span><span id={`${id}-value`} className="wl-combobox-value">{selectedLabel}</span><span className="wl-combobox-chevron" aria-hidden="true">▾</span>
    </button>
    {open && !disabled && <div className="wl-combobox-popover"><input type="search" autoFocus value={query} placeholder={searchLabel} aria-label={searchLabel} role="combobox" aria-expanded="true" aria-controls={listId} aria-activedescendant={visibleItems[activeIndex] ? `${id}-${getKey(visibleItems[activeIndex])}` : undefined} onChange={(event) => { setQuery(event.target.value); setActiveIndex(0) }} onKeyDown={onSearchKeyDown} /><div id={listId} className="wl-combobox-options" role="listbox" aria-label={`${label} results`}>{visibleItems.map((item, index) => <button type="button" key={getKey(item)} id={`${id}-${getKey(item)}`} role="option" aria-selected={selected !== null && getKey(item) === getKey(selected)} className={index === activeIndex ? 'active' : ''} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(item)}><span>{getLabel(item)}</span>{getMeta?.(item) && <small>{getMeta(item)}</small>}</button>)}{!visibleItems.length && <p className="wl-combobox-empty">{emptyLabel}</p>}</div></div>}
  </div>
}

function Brand({ action }: { action?: ReactNode }) {
  return <header className="wl-header"><button className="wl-brand" onClick={() => { window.history.pushState(null, '', '/'); window.dispatchEvent(new PopStateEvent('popstate')) }}>Whyline</button>{action}</header>
}

export function Landing({ navigate }: { navigate: (path: string) => void }) {
  return <main className="wl-public"><Brand action={<nav><button className="wl-text-button" onClick={() => navigate('/login')}>Sign in</button><button className="wl-button" onClick={() => navigate('/signup')}>Get started</button></nav>} /><section className="wl-hero"><p className="wl-kicker">Grounded incident analysis</p><h1>Find the change behind the incident.</h1><p>Connect your engineering sources once, then trace production failures to the code that changed.</p><div className="wl-actions"><button className="wl-button" onClick={() => navigate('/signup')}>Get started</button><button className="wl-text-button" onClick={() => navigate('/login')}>Sign in</button></div></section></main>
}

export function AuthPage({ mode, navigate, onAuthenticated }: { mode: 'login' | 'signup', navigate: (path: string) => void, onAuthenticated: (user: AuthenticatedUser) => void }) {
  const [name, setName] = useState(''); const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [error, setError] = useState<string | null>(null); const [saving, setSaving] = useState(false)
  const signup = mode === 'signup'
  async function submit(event: FormEvent) { event.preventDefault(); if (saving) return; setSaving(true); setError(null); try { onAuthenticated(signup ? await registerWorkspace(email, password) : await loginWorkspace(email, password)) } catch (caught) { setError(errorMessage(caught)) } finally { setSaving(false) } }
  return <main className="wl-public"><Brand /><section className="wl-auth"><div><p className="wl-kicker">Your workspace</p><h1>{signup ? 'Create your account.' : 'Welcome back.'}</h1><p>Connect sources once. Keep incident investigation grounded in provider evidence.</p></div><form className="wl-card wl-auth-card" onSubmit={submit}>{signup && <label>Name<input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" required /></label>}<label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required /></label><label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={signup ? 'new-password' : 'current-password'} required /></label>{error && <p role="alert" className="wl-error">{error}</p>}<button className="wl-button" disabled={saving}>{saving ? 'Please wait…' : signup ? 'Create account' : 'Sign in'}</button><p className="wl-small">{signup ? 'Already have an account?' : 'New to Whyline?'} <button type="button" className="wl-link" onClick={() => navigate(signup ? '/login' : '/signup')}>{signup ? 'Sign in' : 'Create account'}</button></p></form></section></main>
}

function ProviderDialog({ provider, onClose, onSaved }: { provider: CredentialProvider, onClose: () => void, onSaved: () => void }) {
  const [token, setToken] = useState(''); const [saving, setSaving] = useState(false); const [error, setError] = useState<string | null>(null)
  const name = providers.find((item) => item.id === provider)?.name ?? provider
  async function submit(event: FormEvent) { event.preventDefault(); setSaving(true); setError(null); try { await connectCredential(provider, token); onSaved() } catch (caught) { setError(errorMessage(caught)) } finally { setSaving(false) } }
  useEffect(() => { const escape = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') onClose() }; window.addEventListener('keydown', escape); return () => window.removeEventListener('keydown', escape) }, [onClose])
  return <div className="wl-modal-backdrop" role="presentation" onMouseDown={onClose}><form className="wl-card wl-modal" role="dialog" aria-modal="true" aria-labelledby="credential-title" onMouseDown={(event) => event.stopPropagation()} onSubmit={submit}><h2 id="credential-title">Connect {name}</h2><p>Store the credential required by the connected provider.</p><label>{name} token<input type="password" autoFocus autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} required /></label>{error && <p role="alert" className="wl-error">{error}</p>}<div className="wl-actions"><button className="wl-button" disabled={saving}>{saving ? 'Connecting…' : 'Connect'}</button><button type="button" className="wl-text-button" onClick={onClose}>Cancel</button></div></form></div>
}

function SourceCards({ connections, refresh }: { connections: CredentialConnections | null, refresh: () => Promise<void> }) {
  const [editing, setEditing] = useState<CredentialProvider | null>(null); const [error, setError] = useState<string | null>(null); const [removing, setRemoving] = useState<CredentialProvider | null>(null)
  async function remove(provider: CredentialProvider) { setRemoving(provider); setError(null); try { await disconnectCredential(provider); await refresh() } catch (caught) { setError(errorMessage(caught)) } finally { setRemoving(null) } }
  return <>{error && <p role="alert" className="wl-error">{error}</p>}<div className="wl-source-list">{providers.map((provider) => { const connection = connections?.[provider.id]; const connected = connection?.connected === true; return <article className="wl-source-row" key={provider.id}><div><h2>{provider.name}</h2><p className={connected ? 'wl-connected' : ''}>{connections === null ? 'Checking connection…' : connected ? 'Connected' : provider.required ? 'Not connected' : 'Optional'}</p></div>{connected ? <button className="wl-text-button" disabled={removing === provider.id} onClick={() => void remove(provider.id)}>{removing === provider.id ? 'Disconnecting…' : 'Disconnect'}</button> : <button className="wl-button wl-button-small" disabled={connections === null} onClick={() => setEditing(provider.id)}>Connect</button>}</article> })}</div>{editing && <ProviderDialog provider={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void refresh() }} />}</>
}

function SourceStatus({ connections }: { connections: CredentialConnections | null }) {
  return <div className="wl-source-status" aria-label="Source connection status">{providers.map((provider) => { const connected = connections?.[provider.id].connected === true; const label = connected ? `${provider.name} connected` : provider.required ? `${provider.name} not connected` : 'Jira optional'; return <span className={connected ? 'connected' : ''} key={provider.id}><i aria-hidden="true" />{label}</span> })}</div>
}

function ScanWorkspace({ connections, navigate }: { connections: CredentialConnections | null, navigate: (path: string) => void }) {
  const [github, setGithub] = useState<GitHubContext | null>(null); const [projects, setProjects] = useState<SentryProject[] | null>(null)
  const [selectedRepository, setSelectedRepository] = useState<GitHubRepository | null>(null); const [selectedSentryProject, setSelectedSentryProject] = useState<SentryProject | null>(null)
  const [githubError, setGithubError] = useState<string | null>(null); const [sentryError, setSentryError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false); const [result, setResult] = useState<CorrelationScanResult | null>(null); const [error, setError] = useState<string | null>(null); const [selected, setSelected] = useState<CorrelationIssue | null>(null)
  const githubConnected = connections?.github.connected === true; const sentryConnected = connections?.sentry.connected === true
  useEffect(() => { let active = true; setGithub(null); setProjects(null); setSelectedRepository(null); setSelectedSentryProject(null); setGithubError(null); setSentryError(null); setResult(null); if (githubConnected) void fetchGitHubContext().then((context) => { if (active) setGithub(context) }).catch((caught) => { if (active) setGithubError(discoveryErrorMessage('GitHub', caught)) }); if (sentryConnected) void fetchSentryProjects().then((items) => { if (active) setProjects(items) }).catch((caught) => { if (active) setSentryError(discoveryErrorMessage('Sentry', caught)) }); return () => { active = false } }, [githubConnected, sentryConnected])
  const request = correlationRequestForSelection(selectedRepository, selectedSentryProject); const canScan = canAnalyzeRepositoryScan(githubConnected, sentryConnected, selectedRepository, selectedSentryProject, Boolean(githubError || sentryError)); const githubLoading = githubConnected && github === null && !githubError; const sentryLoading = sentryConnected && projects === null && !sentryError
  async function scan(event: FormEvent) { event.preventDefault(); if (!request) { setError('Select an accessible repository and Sentry project.'); return }; setLoading(true); setError(null); try { setResult(await runCorrelationScan(request)); setSelected(null) } catch (caught) { setError(scanErrorMessage(caught)) } finally { setLoading(false) } }
  if (selected) return <Diagnosis issue={selected} repositoryName={result?.repository_name ?? null} onBack={() => setSelected(null)} />
  const grounded = result?.results.filter((issue) => issue.analysis.status === 'completed').length ?? 0; const insufficient = result?.results.filter((issue) => issue.analysis.status === 'insufficient_evidence').length ?? 0
  return <section className="wl-workspace-content wl-scan-content">{!result ? <><div className="wl-title-row"><div><h1>Repository scan</h1><p>Trace production incidents back to the code change that introduced them.</p></div></div><form className="wl-scan-form" onSubmit={scan}><DiscoveryCombobox id="repository" label="Repository" searchLabel="Search repositories…" emptyLabel="No repositories found" loadingLabel="Loading repositories…" providerMark="GH" items={github?.repositories ?? []} selected={selectedRepository} disabled={!githubConnected || githubLoading || Boolean(githubError)} loading={githubLoading} getKey={(item) => item.full_name} getLabel={(item) => `${item.owner} / ${item.name}`} getSearchText={(item) => `${item.owner} ${item.name} ${item.full_name}`} getMeta={(item) => item.private ? 'Private' : 'Public'} onSelect={setSelectedRepository} /><DiscoveryCombobox id="sentry-project" label="Sentry project" searchLabel="Search Sentry projects…" emptyLabel="No Sentry projects found" loadingLabel="Loading Sentry projects…" providerMark="S" items={projects ?? []} selected={selectedSentryProject} disabled={!sentryConnected || sentryLoading || Boolean(sentryError)} loading={sentryLoading} getKey={(item) => `${item.organization_slug}/${item.project_slug}`} getLabel={(item) => `${item.organization_slug} / ${item.project_slug}`} getSearchText={(item) => `${item.organization_slug} ${item.project_slug} ${item.name}`} onSelect={setSelectedSentryProject} /><SourceStatus connections={connections} /><button className="wl-button wl-scan-cta" disabled={loading || !canScan}>{loading ? 'Analyzing repository…' : 'Analyze repository'}</button></form>{!githubConnected && connections !== null && <p className="wl-required">Connect GitHub to choose a repository. <button className="wl-link" onClick={() => navigate('/sources')}>Manage sources</button></p>}{!sentryConnected && connections !== null && <p className="wl-required">Connect Sentry to choose a project. <button className="wl-link" onClick={() => navigate('/sources')}>Manage sources</button></p>}{githubError && <p role="alert" className="wl-error">{githubError}</p>}{sentryError && <p role="alert" className="wl-error">{sentryError}</p>}{github?.repositories.length === 0 && <p className="wl-required">No repositories found for this GitHub connection.</p>}{projects?.length === 0 && <p className="wl-required">No Sentry projects found for this connection.</p>}{error && <p role="alert" className="wl-error">{error}</p>}{loading && <div className="wl-loading" role="status"><span className="wl-spinner" /><div><strong>Analyzing repository…</strong><p>Correlating Sentry issues with commits and code changes.</p></div></div>}</> : <section className="wl-results"><div className="wl-selected-source-bar"><div><strong>{selectedRepository ? `${selectedRepository.owner} / ${selectedRepository.name}` : result.repository_owner}</strong><span>{selectedSentryProject ? `${selectedSentryProject.organization_slug} / ${selectedSentryProject.project_slug}` : 'Selected Sentry project'}</span></div><button className="wl-text-button" onClick={() => setResult(null)}>Change</button></div><div className="wl-summary"><strong>{result.total_open_issues_found} open issue{result.total_open_issues_found === 1 ? '' : 's'}</strong><span>{grounded} grounded</span><span>{insufficient} insufficient evidence</span>{result.truncated && <span>Results limited to scanned issues</span>}</div>{result.results.map((issue) => <IssueCard key={issue.sentry_issue_id} issue={issue} repositoryName={result.repository_name} onView={() => setSelected(issue)} />)}</section>}</section>
}

export function IssueCard({ issue, repositoryName, onView }: { issue: CorrelationIssue, repositoryName?: string | null, onView: () => void }) {
  const finding = issue.analysis.code_findings[0]; const p = issue.presentation
  const location = locationParts(p.failure_file_path, p.failure_line_number, p.failure_function_name, repositoryName)
  return <article className="wl-card wl-issue"><div className="wl-issue-head"><div><code>{issue.sentry_short_id}</code>{p.issue_title && <h2>{p.issue_title}</h2>}{location.length > 0 && <p>{location.join(' · ')}</p>}</div><div className="wl-badges"><span className={`wl-badge ${issue.status === 'partial' ? 'wl-badge-warn' : ''}`}>{issue.status === 'ok' ? 'Correlation OK' : issue.status === 'partial' ? 'Partial correlation' : 'Correlation unavailable'}</span><span className="wl-badge">{analysisLabel(issue.analysis.status)}</span></div></div><dl className="wl-issue-details"><div><dt>Category</dt><dd>{finding ? categoryLabel(finding.category) : 'Not established'}</dd></div><div><dt>Grounding</dt><dd>{groundingLabel(p.grounding_strength)}</dd></div></dl><div className="wl-metadata">{issue.commit_sha && <code>Commit {issue.commit_sha.slice(0, 7)}</code>}{issue.jira_ticket && <code>Jira {issue.jira_ticket}</code>}</div>{p.fact_summaries[0]?.detail && <p className="wl-issue-summary">{p.fact_summaries[0].detail}</p>}<button className="wl-text-button" onClick={onView}>View diagnosis →</button></article>
}

export function ProposedFixPanel({ fix }: { fix: CorrelationIssue['analysis']['proposed_fixes'][number] }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    await navigator.clipboard.writeText(fix.corrected_hunk)
    setCopied(true)
  }
  const diff = computeLineDiff(fix.original_hunk, fix.corrected_hunk)
  const hasChange = diff.some((line) => line.kind !== 'context')
  return <section className="wl-card wl-panel wl-proposed-fix">
    <div className="wl-fix-title">
      <h2>Proposed fix</h2>
      <button className="wl-text-button" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy patch'}</button>
    </div>
    <h3>Failure mechanism</h3>
    <p>{fix.failure_mechanism}</p>
    <h3>Fix strategy</h3>
    <p>{fix.fix_strategy}</p>
    <h3>Patch</h3>
    {hasChange
      ? <pre className="wl-diff"><code>{diff.map((line, index) => (
          <div key={index} className={`wl-diff-line wl-diff-${line.kind}`}>
            {(line.kind === 'added' ? '+ ' : line.kind === 'removed' ? '- ' : '  ') + line.text}
          </div>
        ))}</code></pre>
      : <pre className="wl-diff"><code>{fix.corrected_hunk}</code></pre>}
    <h3>Why this fixes it</h3>
    <p>{fix.explanation}</p>
    <p className="wl-small">This grounded, scope-validated suggestion is not automatically applied or proven correct until tested.</p>
  </section>
}

function CodeFindingGroupCard({ group, repositoryName }: { group: WhylineCodeFindingGroup, repositoryName?: string | null }) {
  const [expanded, setExpanded] = useState(false)
  const { primary, supportingCount, duplicates } = group
  const relativePath = primary.file_path ? repositoryRelativePath(primary.file_path, repositoryName) : null
  const meta = [primary.function_name ? `${primary.function_name}()` : null, primary.line_number !== null ? `Line ${primary.line_number}` : null]
    .filter(Boolean).join(' · ')
  return <div className="wl-finding">
    {relativePath && <code className="wl-finding-path">{relativePath}</code>}
    {meta && <p className="wl-finding-meta">{meta}</p>}
    <p className="wl-finding-label">{categoryLabel(primary.category)}</p>
    <p>{primary.statement}</p>
    {supportingCount > 1 && <div className="wl-finding-evidence">
      <button type="button" className="wl-text-button" onClick={() => setExpanded((current) => !current)}>
        {expanded ? 'Hide evidence' : `Supported by ${supportingCount} evidence items`}
      </button>
      {expanded && <ul>{duplicates.map((duplicate, index) => <li key={index}>{duplicate.statement}</li>)}</ul>}
    </div>}
  </div>
}

export function Diagnosis({ issue, repositoryName, onBack }: { issue: CorrelationIssue, repositoryName?: string | null, onBack: () => void }) {
  const p = issue.presentation; const a = issue.analysis
  const location = locationParts(p.failure_file_path, p.failure_line_number, p.failure_function_name, repositoryName)
  const summary = failureSummary(issue)
  const codeFindingGroups = groupCodeFindings(a.code_findings)
  const primaryHypothesis = a.hypotheses[0]?.statement ?? null
  const primaryFinding = a.code_findings[0] ?? null
  const primaryFindingLocation = primaryFinding
    ? locationParts(primaryFinding.file_path, primaryFinding.line_number, null, repositoryName).join(' · ')
    : ''
  const groundedIn = primaryFindingLocation ? [primaryFindingLocation] : []
  if (issue.commit_sha) groundedIn.push(`Commit ${issue.commit_sha.slice(0, 7)}`)
  groundedIn.push(`Sentry ${issue.sentry_short_id}`)
  const noEvidence = a.status === 'insufficient_evidence'; const noHypothesis = a.status === 'no_validated_hypothesis'
  return <section className="wl-workspace-content wl-diagnosis-content">
    <button className="wl-text-button" onClick={onBack}>← Back to scan</button>
    <div className="wl-title-row">
      <div>
        <code>{issue.sentry_short_id}</code>
        {p.issue_title && <h1>{p.issue_title}</h1>}
        {summary && <p className="wl-failure-summary">{summary}</p>}
      </div>
      <div className="wl-badges">
        <span className="wl-badge">{issue.status === 'ok' ? 'Correlation OK' : issue.status === 'partial' ? 'Partial correlation' : 'Correlation unavailable'}</span>
        <span className="wl-badge">{analysisLabel(a.status)}</span>
      </div>
    </div>
    <div className="wl-diagnosis-grid">
      <div>
        {primaryHypothesis && <section className="wl-card wl-panel">
          <h2>Likely cause</h2>
          <p>{primaryHypothesis}</p>
          {groundedIn.length > 0 && <>
            <p className="wl-grounded-in-label">Grounded in</p>
            <ul className="wl-grounded-in">{groundedIn.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </>}
        </section>}
        <section className="wl-card wl-panel">
          <h2>Code finding</h2>
          {codeFindingGroups.length
            ? codeFindingGroups.map((group, index) => <CodeFindingGroupCard key={index} group={group} repositoryName={repositoryName} />)
            : <p>{noEvidence ? 'Whyline found source context but not enough deterministic evidence to make a grounded diagnosis.' : noHypothesis ? 'The available evidence did not support a reliable causal explanation.' : 'A grounded code location could not be established.'}</p>}
        </section>
        {a.proposed_fixes.map((fix) => <ProposedFixPanel key={fix.finding_id} fix={fix} />)}
        {a.recommendations.length > 0 && <section className="wl-card wl-panel">
          <h2>Recommended next actions</h2>
          <ol>{a.recommendations.map((recommendation, index) => <li key={index}>{recommendation.message}</li>)}</ol>
        </section>}
        <section className="wl-card wl-panel">
          <h2>Why this is grounded</h2>
          {p.fact_summaries.length
            ? <ul className="wl-facts">{p.fact_summaries.map((fact, index) => <li key={index}><span aria-hidden="true">✓</span><div><strong>{fact.label}</strong>{fact.detail && <p>{fact.detail}</p>}</div></li>)}</ul>
            : <p>No frontend-safe fact summaries were returned.</p>}
        </section>
      </div>
      <aside className="wl-card wl-panel">
        <h2>Diagnosis</h2>
        <dl>
          <dt>Category</dt><dd>{a.code_findings[0] ? categoryLabel(a.code_findings[0].category) : 'Not established'}</dd>
          <dt>Grounding</dt><dd>{groundingLabel(p.grounding_strength)}</dd>
          <dt>Sentry</dt><dd>{issue.sentry_short_id}</dd>
          {issue.jira_ticket && <><dt>Jira</dt><dd>{issue.jira_ticket}</dd></>}
          {issue.commit_sha && <><dt>Commit</dt><dd>{issue.commit_sha.slice(0, 7)}</dd></>}
          {location.length > 0 && <><dt>Failure location</dt><dd>{location.join(' · ')}</dd></>}
        </dl>
        {issue.status === 'partial' && <p className="wl-required">Partial correlation: some source data was unavailable.</p>}
      </aside>
    </div>
  </section>
}

export function WhylineWorkspace({ user, page, navigate, onLogout }: { user: AuthenticatedUser, page: 'scan' | 'sources' | 'connect', navigate: (path: string) => void, onLogout: () => void }) {
  const [connections, setConnections] = useState<CredentialConnections | null>(null); const [error, setError] = useState<string | null>(null); const [accountOpen, setAccountOpen] = useState(false)
  async function refresh() { try { setConnections(await fetchCredentialConnections()) } catch (caught) { setError(errorMessage(caught)) } }
  useEffect(() => { void refresh() }, [])
  async function logout() { try { await logoutWorkspace(); onLogout() } catch (caught) { setError(errorMessage(caught)) } }
  const content = page === 'sources' || page === 'connect' ? <section className="wl-workspace-content wl-sources-content"><div className="wl-title-row"><div><h1>{page === 'connect' ? 'Connect your sources' : 'Sources'}</h1><p>GitHub and Sentry are required for repository scans. Jira adds ticket context when available.</p></div></div><SourceCards connections={connections} refresh={refresh} /><button className="wl-button" onClick={() => navigate('/scan')}>Open repository scan</button></section> : <ScanWorkspace connections={connections} navigate={navigate} />
  return <main className="wl-app"><Brand action={<div className="wl-account"><button className="wl-account-trigger" aria-expanded={accountOpen} aria-haspopup="menu" onClick={() => setAccountOpen((open) => !open)}>{user.email}<span aria-hidden="true">▾</span></button>{accountOpen && <div className="wl-account-menu" role="menu"><button role="menuitem" onClick={() => void logout()}>Log out</button></div>}</div>} /><div className="wl-layout"><nav className="wl-nav" aria-label="Workspace"><button className={page === 'scan' ? 'active' : ''} onClick={() => navigate('/scan')}>Repository Scan</button><button className={page === 'sources' || page === 'connect' ? 'active' : ''} onClick={() => navigate('/sources')}>Sources</button></nav><main className="wl-main">{error && <p role="alert" className="wl-error">{error}</p>}{content}</main></div></main>
}
