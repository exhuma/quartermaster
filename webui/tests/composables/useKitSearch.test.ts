import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import { api } from '@/api'
import { useKitSearch } from '@/composables/useKitSearch'

const mockApi = api as unknown as {
  get: ReturnType<typeof vi.fn>
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useKitSearch', () => {
  it('populates results from the API with an encoded query', async () => {
    mockApi.get.mockResolvedValue({
      query: 'fastapi',
      results: [
        {
          name: 'module-fastapi',
          version: 'v1',
          score: 30,
          summary: 'FastAPI conventions.',
          matched_fields: ['frameworks:fastapi'],
          sections: [],
        },
      ],
    })
    const { results, search } = useKitSearch()
    await search('fast api')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/search?q=fast%20api&limit=20'
    )
    expect(results.value).toHaveLength(1)
    expect(results.value[0].name).toBe('module-fastapi')
  })

  it('captures an error message on failure', async () => {
    mockApi.get.mockRejectedValue(new Error('boom'))
    const { error, search } = useKitSearch()
    await search('anything')
    expect(error.value).toBe('boom')
  })

  it('clears results and error', async () => {
    mockApi.get.mockResolvedValue({
      query: 'x',
      results: [
        {
          name: 'k',
          version: 'v1',
          score: 1,
          summary: '',
          matched_fields: [],
          sections: [],
        },
      ],
    })
    const { results, error, search, clear } = useKitSearch()
    await search('x')
    expect(results.value).toHaveLength(1)
    clear()
    expect(results.value).toHaveLength(0)
    expect(error.value).toBeNull()
  })
})
