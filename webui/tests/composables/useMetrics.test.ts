import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  api: { get: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

import { api } from '@/api'
import { useMetrics } from '@/composables/useMetrics'

const mockApi = api as unknown as { get: ReturnType<typeof vi.fn> }

function fakeOverview(): unknown {
  return {
    meta: {
      window: '7d',
      generated_at: 0,
      retention_days: 7,
      store_enabled: true,
      otel_status: 'inert',
    },
    kit_usage: [{ kit: 'kit-a', deliveries: 3, tokens: 300 }],
    tokens_timeseries: [],
    resolve_health: {
      total_calls: 0,
      engine_mix: {},
      confidence_mix: {},
      coverage_p50: 0,
      coverage_p95: 0,
      broadening_rate: 0,
    },
    tool_latency: [],
    co_occurrence: { kits: [], cells: [] },
    structural_overlap: { kits: [], cells: [] },
    catalog_growth: { catalog: [], delivered: [] },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useMetrics', () => {
  it('fetches the overview for the default window', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { overview, fetchMetrics } = useMetrics()
    await fetchMetrics()
    expect(mockApi.get).toHaveBeenCalledWith('/api/metrics/overview?window=7d')
    expect(overview.value?.kit_usage[0].kit).toBe('kit-a')
  })

  it('switches window and refetches with the new window', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { window, setWindow } = useMetrics()
    await setWindow('24h')
    expect(window.value).toBe('24h')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/metrics/overview?window=24h'
    )
  })

  it('does not refetch when the window is unchanged', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { setWindow } = useMetrics()
    await setWindow('24h') // already 24h from the previous test's singleton state
    expect(mockApi.get).not.toHaveBeenCalled()
  })

  it('captures an error message on failure', async () => {
    mockApi.get.mockRejectedValue(new Error('boom'))
    const { error, fetchMetrics } = useMetrics()
    await fetchMetrics()
    expect(error.value).toBe('boom')
  })
})
