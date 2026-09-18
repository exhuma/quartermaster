import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import { api } from '@/api'
import { usePrompts } from '@/composables/usePrompts'

const mockApi = api as unknown as {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('usePrompts', () => {
  it('populates prompts from the API', async () => {
    mockApi.get.mockResolvedValue([
      {
        name: 'p',
        title: 't',
        description: 'd',
        source_layer: 'base',
        editable: true,
      },
    ])
    const { prompts, fetchPrompts } = usePrompts()
    await fetchPrompts()
    expect(prompts.value).toHaveLength(1)
    expect(mockApi.get).toHaveBeenCalledWith('/api/prompts')
  })

  it('captures an error message on failure', async () => {
    mockApi.get.mockRejectedValue(new Error('boom'))
    const { error, fetchPrompts } = usePrompts()
    await fetchPrompts()
    expect(error.value).toBe('boom')
  })

  it('fetches a single prompt detail', async () => {
    mockApi.get.mockResolvedValue({
      name: 'p',
      title: 't',
      description: 'd',
      source_layer: 'base',
      editable: true,
      body: 'body text',
    })
    const { fetchPrompt } = usePrompts()
    const detail = await fetchPrompt('p')
    expect(mockApi.get).toHaveBeenCalledWith('/api/prompts/p')
    expect(detail.body).toBe('body text')
  })

  it('posts a new prompt on create then refetches', async () => {
    mockApi.post.mockResolvedValue({})
    mockApi.get.mockResolvedValue([])
    const { createPrompt } = usePrompts()
    await createPrompt('release-notes', 'Title', 'Desc', 'Body')
    const [path, body] = mockApi.post.mock.calls[0]
    expect(path).toBe('/api/prompts')
    expect(body).toEqual({
      name: 'release-notes',
      title: 'Title',
      description: 'Desc',
      body: 'Body',
    })
    expect(mockApi.get).toHaveBeenCalled()
  })

  it('puts an updated prompt then refetches', async () => {
    mockApi.put.mockResolvedValue({})
    mockApi.get.mockResolvedValue([])
    const { updatePrompt } = usePrompts()
    await updatePrompt('release-notes', 'Title', 'Desc', 'Body')
    const [path, body] = mockApi.put.mock.calls[0]
    expect(path).toBe('/api/prompts/release-notes')
    expect(body).toEqual({ title: 'Title', description: 'Desc', body: 'Body' })
    expect(mockApi.get).toHaveBeenCalled()
  })

  it('deletes a prompt then refetches', async () => {
    mockApi.delete.mockResolvedValue(null)
    mockApi.get.mockResolvedValue([])
    const { deletePrompt } = usePrompts()
    await deletePrompt('release-notes')
    expect(mockApi.delete).toHaveBeenCalledWith('/api/prompts/release-notes')
    expect(mockApi.get).toHaveBeenCalled()
  })
})
