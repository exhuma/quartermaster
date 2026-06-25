import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import { api } from '@/api'
import { useAppTokens } from '@/composables/useAppTokens'

const mockApi = api as unknown as {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useAppTokens', () => {
  it('mints a token and refreshes the list', async () => {
    mockApi.post.mockResolvedValue({ id: '1', token: 'secret', label: 'l' })
    mockApi.get.mockResolvedValue([{ id: '1', label: 'l' }])
    const { mint, tokens } = useAppTokens()
    const minted = await mint('l')
    expect(minted.token).toBe('secret')
    expect(mockApi.post).toHaveBeenCalledWith('/api/app-tokens', {
      label: 'l',
    })
    expect(tokens.value).toHaveLength(1)
  })

  it('revokes by id then refreshes', async () => {
    mockApi.delete.mockResolvedValue(null)
    mockApi.get.mockResolvedValue([])
    const { revoke } = useAppTokens()
    await revoke('abc')
    expect(mockApi.delete).toHaveBeenCalledWith('/api/app-tokens/abc')
    expect(mockApi.get).toHaveBeenCalled()
  })
})
