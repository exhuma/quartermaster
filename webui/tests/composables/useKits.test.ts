import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import { api } from '@/api'
import { useKits } from '@/composables/useKits'

const mockApi = api as unknown as {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useKits', () => {
  it('populates kits from the API', async () => {
    mockApi.get.mockResolvedValue([
      {
        name: 'k',
        description: 'd',
        versions: ['v1'],
        latest_version: 'v1',
        source_layer: 'base',
      },
    ])
    const { kits, fetchKits } = useKits()
    await fetchKits()
    expect(kits.value).toHaveLength(1)
    expect(mockApi.get).toHaveBeenCalledWith('/api/kits')
  })

  it('captures an error message on failure', async () => {
    mockApi.get.mockRejectedValue(new Error('boom'))
    const { error, fetchKits } = useKits()
    await fetchKits()
    expect(error.value).toBe('boom')
  })

  it('posts a skeleton kit on create then refetches', async () => {
    mockApi.post.mockResolvedValue({})
    mockApi.get.mockResolvedValue([])
    const { createKit } = useKits()
    await createKit('module-new', 'A summary')
    const [path, body] = mockApi.post.mock.calls[0]
    expect(path).toBe('/api/kits')
    expect(body.name).toBe('module-new')
    expect(body.sections[0].always_load).toBe(true)
    expect(mockApi.get).toHaveBeenCalled()
  })

  it('deletes a kit then refetches', async () => {
    mockApi.delete.mockResolvedValue(null)
    mockApi.get.mockResolvedValue([])
    const { deleteKit } = useKits()
    await deleteKit('module-old')
    expect(mockApi.delete).toHaveBeenCalledWith('/api/kits/module-old')
    expect(mockApi.get).toHaveBeenCalled()
  })
})
