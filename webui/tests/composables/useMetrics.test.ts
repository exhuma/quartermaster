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
      granularity: '1d',
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
  it('fetches the overview for the default window and granularity', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { overview, fetchMetrics } = useMetrics()
    await fetchMetrics()
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/metrics/overview?window=7d&granularity=1d'
    )
    expect(overview.value?.kit_usage[0].kit).toBe('kit-a')
  })

  it('switches to 24h and defaults granularity to hourly', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { window, granularity, setWindow } = useMetrics()
    await setWindow('24h')
    expect(window.value).toBe('24h')
    expect(granularity.value).toBe('1h')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/metrics/overview?window=24h&granularity=1h'
    )
  })

  it('does not refetch when the window is unchanged', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { setWindow } = useMetrics()
    await setWindow('24h') // already 24h from the previous test's singleton state
    expect(mockApi.get).not.toHaveBeenCalled()
  })

  it('overrides granularity for the current window and refetches', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { granularity, setGranularity } = useMetrics()
    await setGranularity('1d') // window is still 24h from earlier
    expect(granularity.value).toBe('1d')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/metrics/overview?window=24h&granularity=1d'
    )
  })

  it('does not refetch when the granularity is unchanged', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { setGranularity } = useMetrics()
    await setGranularity('1d') // already 1d from the previous test
    expect(mockApi.get).not.toHaveBeenCalled()
  })

  it('resets granularity to daily on wider windows', async () => {
    mockApi.get.mockResolvedValue(fakeOverview())
    const { granularity, setWindow } = useMetrics()
    await setWindow('7d')
    expect(granularity.value).toBe('1d')
    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/metrics/overview?window=7d&granularity=1d'
    )
  })

  it('captures an error message on failure', async () => {
    mockApi.get.mockRejectedValue(new Error('boom'))
    const { error, fetchMetrics } = useMetrics()
    await fetchMetrics()
    expect(error.value).toBe('boom')
  })
})
