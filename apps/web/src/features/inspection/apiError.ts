/** Error type shared by HTTP transport and runtime response validation. */

export class ConnectorApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ConnectorApiError'
    this.status = status
  }
}
