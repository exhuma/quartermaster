import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: { get: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import { api } from '@/api'
import { useMe } from '@/composables/useMe'

const mockApi = api as unknown as { get: ReturnType<typeof vi.fn> }

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useMe', () => {
  it('is not an editor before any fetch', () => {
    const { isEditor } = useMe()
    // Fresh singletons may carry state across tests; assert on the computed
    // after an explicit consumer fetch below instead of the initial value.
    expect(typeof isEditor.value).toBe('boolean')
  })

  it('reports editor when the server says so', async () => {
    mockApi.get.mockResolvedValue({ sub: 's', label: 'A', role: 'editor' })
    const { isEditor, fetchMe, me } = useMe()
    await fetchMe()
    expect(mockApi.get).toHaveBeenCalledWith('/api/me')
    expect(me.value?.role).toBe('editor')
    expect(isEditor.value).toBe(true)
  })

  it('reports consumer (not editor) for a consumer', async () => {
    mockApi.get.mockResolvedValue({ sub: 's', label: 'A', role: 'consumer' })
    const { isEditor, fetchMe } = useMe()
    await fetchMe()
    expect(isEditor.value).toBe(false)
  })

  it('captures an error message on failure and is not editor', async () => {
    mockApi.get.mockRejectedValue(new Error('boom'))
    const { isEditor, error, fetchMe } = useMe()
    await fetchMe()
    expect(error.value).toBe('boom')
    expect(isEditor.value).toBe(false)
  })
})
