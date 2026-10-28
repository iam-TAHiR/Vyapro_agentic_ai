export class ApiError extends Error {
  readonly status?: number
  readonly code?: string

  constructor(message: string, status?: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export type ApiClientOptions = {
  baseUrl: string
  fetchImpl?: typeof fetch
}

export function createApiClient({ baseUrl, fetchImpl = fetch }: ApiClientOptions) {
  async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body && !(typeof FormData !== 'undefined' && init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })

    let body: unknown
    try {
      body = await response.json()
    } catch {
      throw new ApiError('The server response was not valid JSON.', response.status)
    }

    if (!response.ok) {
      const payload = body && typeof body === 'object' ? body as { error?: { message?: string; code?: string } } : {}
      const error = payload.error
      throw new ApiError(error?.message ?? `Request failed with status ${response.status}.`, response.status, error?.code)
    }

    return body as T
  }

  return { requestJson }
}
