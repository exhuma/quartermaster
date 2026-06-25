// Central HTTP client (module-vue-vuetify). All API calls go through here.
// Vanilla fetch — no axios. Sends the vendor media type the server's strict
// content negotiation requires on both Accept and Content-Type.

import { apiBaseUrl } from '@/config'

export const VENDOR_MEDIA_TYPE = 'application/vnd.instructions+json; v=1'

export class ApiError extends Error {
  status: number
  data: unknown

  constructor(status: number, data: unknown, message?: string) {
    super(message ?? `Request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

// Authentication seam. The default reads a token from localStorage; the
// OIDC bootstrap (main.ts) replaces it with an oidc-client-ts-backed one.
export interface TokenProvider {
  getToken(): string | null | Promise<string | null>
}

let tokenProvider: TokenProvider = {
  getToken: () => localStorage.getItem('access_token'),
}

export function setTokenProvider(provider: TokenProvider): void {
  tokenProvider = provider
}

let unauthorizedHandler: () => void = () => {}

export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler
}

// Symmetric to the unauthorized handler: invoked on every successful response.
// The OIDC bootstrap uses it to reset the re-authentication loop guard.
let authSuccessHandler: () => void = () => {}

export function setAuthSuccessHandler(handler: () => void): void {
  authSuccessHandler = handler
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: VENDOR_MEDIA_TYPE }
  const token = await tokenProvider.getToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const init: RequestInit = { method, headers }
  if (body !== undefined) {
    headers['Content-Type'] = VENDOR_MEDIA_TYPE
    init.body = JSON.stringify(body)
  }

  const response = await fetch(`${apiBaseUrl}${path}`, init)

  if (response.status === 401) {
    unauthorizedHandler()
  } else if (response.ok) {
    authSuccessHandler()
  }

  const data = await parseBody(response)
  if (!response.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : undefined
    throw new ApiError(response.status, data, detail)
  }
  return data as T
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null
  }
  const text = await response.text()
  if (!text) {
    return null
  }
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
