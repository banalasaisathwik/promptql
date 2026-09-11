/** Normalize separators so paths from different collection sources compare equally. */
export function normalizedSlashPath(path: string): string {
  return path.replace(/\\/g, '/').replace(/^\.\//, '')
}

/**
 * Present a repository-relative path instead of the absolute filesystem path
 * a connector observed at runtime (e.g. a Sentry stack frame recorded under
 * `/opt/render/project/src/<repository>/...`). This mirrors the backend's
 * `paths_match` suffix logic (services/api/app/investigations/
 * path_normalization.py) but only for display: it never changes which file
 * the evidence refers to, it only trims the infrastructure prefix in front
 * of the repository root when that root name is present in the path.
 */
export function repositoryRelativePath(filePath: string, repositoryName?: string | null): string {
  const normalized = normalizedSlashPath(filePath)
  if (!repositoryName) return normalized
  const segments = normalized.split('/')
  const rootIndex = segments.lastIndexOf(repositoryName)
  if (rootIndex === -1 || rootIndex === segments.length - 1) return normalized
  return segments.slice(rootIndex + 1).join('/')
}
