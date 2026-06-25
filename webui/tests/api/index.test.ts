import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  api,
  ApiError,
  setAuthSuccessHandler,
  setTokenProvider,
  setUnauthorizedHandler,
  VENDOR_MEDIA_TYPE,
} from '@/api'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': VENDOR_MEDIA_TYPE },
  })
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  setTokenProvider({ getToken: () => null })
  setUnauthorizedHandler(() => {})
  setAuthSuccessHandler(() => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('sends the vendor Accept type and bearer token', async () => {
    setTokenProvider({ getToken: () => 'tok-123' })
    fetchMock.mockResolvedValue(jsonResponse([]))
    await api.get('/api/kits')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers.Accept).toBe(VENDOR_MEDIA_TYPE)
    expect(headers.Authorization).toBe('Bearer tok-123')
  })

  it('sets the vendor Content-Type only when a body is sent', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }))
    await api.post('/api/kits', { a: 1 })
    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers['Content-Type']).toBe(VENDOR_MEDIA_TYPE)
    expect(init.body).toBe(JSON.stringify({ a: 1 }))
  })

  it('throws ApiError carrying status and detail', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'nope' }, 422))
    await expect(api.post('/api/kits', {})).rejects.toMatchObject({
      status: 422,
      message: 'nope',
    })
  })

  it('invokes the unauthorized handler on 401', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'x' }, 401))
    await expect(api.get('/api/kits')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledOnce()
  })

  it('invokes the auth-success handler on a 2xx response', async () => {
    const onSuccess = vi.fn()
    setAuthSuccessHandler(onSuccess)
    fetchMock.mockResolvedValue(jsonResponse([]))
    await api.get('/api/kits')
    expect(onSuccess).toHaveBeenCalledOnce()
  })

  it('returns null for a 204 response', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    expect(await api.delete('/api/kits/x')).toBeNull()
  })
})
