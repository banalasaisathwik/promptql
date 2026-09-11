import type { CorrelationScanRequest, GitHubRepository, SentryProject } from './api'

/** Builds a scan request only from records returned by provider discovery. */
export function correlationRequestForSelection(
  repository: GitHubRepository | null | undefined,
  project: SentryProject | null | undefined,
): CorrelationScanRequest | null {
  if (!repository || !project) return null
  return {
    repository_owner: repository.owner,
    repository_name: repository.name,
    sentry_project_slug: project.project_slug,
  }
}

/** The scan CTA is available only once both required provider selections exist. */
export function canAnalyzeRepositoryScan(
  githubConnected: boolean,
  sentryConnected: boolean,
  repository: GitHubRepository | null | undefined,
  project: SentryProject | null | undefined,
  discoveryHasError: boolean,
): boolean {
  return githubConnected
    && sentryConnected
    && !discoveryHasError
    && correlationRequestForSelection(repository, project) !== null
}
