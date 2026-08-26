export function runPathFor(runId: string): string {
  return `/runs/${encodeURIComponent(runId)}`
}


export function runTracePathFor(runId: string): string {
  return `/runs/${encodeURIComponent(runId)}/trace`
}
