import type { ApiErrorBody } from './types'

// Thin fetch wrapper for contract 05: JSON bodies, the error envelope and X-Request-Id.

export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: { field: string; problem: string }[]
  readonly requestId: string | null

  constructor(status: number, body: ApiErrorBody['error'], requestId: string | null = null) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.fields = body.fields ?? []
    this.requestId = requestId
  }
}

/** Turns a non-2xx response into an ApiError, also when the body is not the contract envelope. */
export async function toApiError(res: Response): Promise<ApiError> {
  const requestId = res.headers.get('X-Request-Id')
  let body: ApiErrorBody['error'] = { code: `HTTP_${res.status}`, message: res.statusText || 'Request failed' }
  try {
    const json = (await res.json()) as Partial<ApiErrorBody>
    if (json.error?.code) body = json.error
  } catch {
    // Body is not JSON. Keep the generic error.
  }
  return new ApiError(res.status, body, requestId)
}

interface RequestOptions {
  body?: unknown
  form?: FormData
  query?: Record<string, string | number | boolean | undefined | null>
  signal?: AbortSignal
}

export function buildUrl(path: string, query?: RequestOptions['query']): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`
}

export async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  let body: BodyInit | undefined
  if (opts.form) {
    body = opts.form
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }

  let res: Response
  try {
    res = await fetch(buildUrl(path, opts.query), { method, headers, body, signal: opts.signal })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(0, { code: 'NETWORK_ERROR', message: 'The service is not reachable.' })
  }

  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}
