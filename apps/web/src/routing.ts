export function runPathFor(runId: string): string {
  return `/runs/${encodeURIComponent(runId)}`
}
