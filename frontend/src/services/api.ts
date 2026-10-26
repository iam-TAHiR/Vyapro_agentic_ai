/**
 * Shared transport utilities for the future confirmed API.
 *
 * Do not read VITE_API_BASE_URL until Flask URL and API contract are confirmed.
 * This module intentionally adds only safe, non-secret request headers; never
 * place keys, credentials, or LLM secrets in browser code or Vite variables.
 */
export class ApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
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
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })

    if (!response.ok) {
      throw new ApiError(`Request failed with status ${response.status}.`, response.status)
    }

    try {
      return (await response.json()) as T
    } catch {
      throw new ApiError('The server response was not valid JSON.', response.status)
    }
  }

  return { requestJson }
}
