import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import { api } from '@/api'
import { useKitEditor } from '@/composables/useKitEditor'

const mockApi = api as unknown as {
  get: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useKitEditor', () => {
  it('builds the correct section paths', async () => {
    mockApi.get.mockResolvedValue({})
    mockApi.put.mockResolvedValue({})
    const e = useKitEditor()
    await e.getSection('module-a', 'v1', 'invariant')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/kits/module-a/versions/v1/sections/invariant',
    )
    await e.saveSection('module-a', 'v1', 'invariant', {
      title: 'T',
      gloss: 'G',
      always_load: true,
      body: 'B',
    })
    const [path, payload] = mockApi.put.mock.calls[0]
    expect(path).toBe('/api/kits/module-a/versions/v1/sections/invariant')
    expect(payload.always_load).toBe(true)
  })

  it('encodes path segments', async () => {
    mockApi.get.mockResolvedValue({})
    const e = useKitEditor()
    await e.getOutline('weird name', 'v1')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/kits/weird%20name/versions/v1/outline',
    )
  })

  it('builds the compare query', async () => {
    mockApi.get.mockResolvedValue({ changes: [], user_facing_warning: false })
    const e = useKitEditor()
    await e.compareVersions('module-a', 'v1.0.0', 'v2.0.0')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/kits/module-a/compare?from=v1.0.0&to=v2.0.0',
    )
  })

  it('caches the trait vocabulary after the first load', async () => {
    mockApi.get.mockResolvedValue({ languages: ['python'] })
    const e = useKitEditor()
    await e.loadTraits()
    await e.loadTraits()
    const traitCalls = mockApi.get.mock.calls.filter(
      (c) => c[0] === '/api/traits',
    )
    expect(traitCalls).toHaveLength(1)
  })

  it('puts applicability to the right path', async () => {
    mockApi.put.mockResolvedValue({})
    const e = useKitEditor()
    await e.saveApplicability('module-a', { priority: 9 } as never)
    expect(mockApi.put).toHaveBeenCalledWith(
      '/api/kits/module-a/applicability',
      { priority: 9 },
    )
  })
})
