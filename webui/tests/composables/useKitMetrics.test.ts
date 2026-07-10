import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: { get: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import { api } from '@/api'
import { useKitMetrics } from '@/composables/useKitMetrics'

const mockApi = api as unknown as { get: ReturnType<typeof vi.fn> }

function fakeAdoption(): unknown {
  return {
    meta: {
      kit: 'kit-alpha',
      window: '30d',
      granularity: '1d',
      generated_at: 0,
      retention_days: 7,
      store_enabled: true,
      available_versions: ['v1', 'v2'],
    },
    granularity: '1d',
    versions: ['v1', 'v2'],
    buckets: [{ day: '2026-01-01', counts: { v1: 2, v2: 1 } }],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useKitMetrics', () => {
  it('fetches per-kit adoption with the default window/granularity', async () => {
    mockApi.get.mockResolvedValue(fakeAdoption())
    const { adoption, fetchAdoption } = useKitMetrics()
    await fetchAdoption('kit-alpha')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/kits/kit-alpha/version-adoption?window=30d&granularity=1d'
    )
    expect(adoption.value?.versions).toEqual(['v1', 'v2'])
    expect(adoption.value?.buckets[0].counts).toEqual({ v1: 2, v2: 1 })
  })

  it('url-encodes the kit name', async () => {
    mockApi.get.mockResolvedValue(fakeAdoption())
    const { fetchAdoption } = useKitMetrics()
    await fetchAdoption('scope/kit')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/kits/scope%2Fkit/version-adoption?window=30d&granularity=1d'
    )
  })

  it('captures the error message on failure', async () => {
    mockApi.get.mockRejectedValue(new Error('boom'))
    const { adoption, error, fetchAdoption } = useKitMetrics()
    await fetchAdoption('kit-alpha')
    expect(adoption.value).toBeNull()
    expect(error.value).toBe('boom')
  })
})
