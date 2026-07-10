import { describe, expect, it } from 'vitest'

import {
  bucketToEpochMs,
  catalogGrowthDomains,
  catalogGrowthOption,
  formatBucketUTC,
  tokensOption,
} from '@/views/metricsCharts'
import type { CatalogGrowth, TokenPoint } from '@/types/metrics'

// A two-domain, two-day bundle. "auth" has catalog on both days but delivery
// only on day 1; "ui" appears on day 2 only — enough to exercise the union of
// domains, per-day summing, and single-domain filtering.
const growth: CatalogGrowth = {
  catalog: [
    {
      day: '2026-01-01',
      domain: 'auth',
      total_tokens: 100,
      always_load_tokens: 10,
    },
    {
      day: '2026-01-01',
      domain: 'ui',
      total_tokens: 40,
      always_load_tokens: 4,
    },
    {
      day: '2026-01-02',
      domain: 'auth',
      total_tokens: 120,
      always_load_tokens: 12,
    },
    {
      day: '2026-01-02',
      domain: 'ui',
      total_tokens: 60,
      always_load_tokens: 6,
    },
  ],
  delivered: [
    { day: '2026-01-01', domain: 'auth', tokens: 30 },
    { day: '2026-01-02', domain: 'ui', tokens: 25 },
  ],
}

// Series data are [epochMs, value] pairs on the time axis. These helpers pull
// the value component (and the x component) back out for assertions.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const pairs = (opt: any, name: string): [number, number][] =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  opt.series.find((s: any) => s.name === name).data
const values = (opt: unknown, name: string): number[] =>
  pairs(opt, name).map((d) => d[1])

const colors = ['#c0', '#c1', '#c2']

describe('bucketToEpochMs', () => {
  it('parses hourly UTC buckets', () => {
    expect(bucketToEpochMs('2026-07-02 13:00')).toBe(Date.UTC(2026, 6, 2, 13))
  })

  it('parses daily UTC buckets to midnight UTC', () => {
    expect(bucketToEpochMs('2026-07-02')).toBe(Date.UTC(2026, 6, 2))
  })
})

describe('formatBucketUTC', () => {
  it('renders the hour for hourly granularity in UTC', () => {
    expect(formatBucketUTC(Date.UTC(2026, 6, 2, 13), '1h')).toBe('Jul 02 13:00')
  })

  it('renders only the date for daily granularity', () => {
    expect(formatBucketUTC(Date.UTC(2026, 6, 2), '1d')).toBe('Jul 02')
  })
})

describe('tokensOption', () => {
  // A two-day hourly fixture: the old category axis stripped the date and
  // collapsed missing hours, so these read out of order and looked like a 24h
  // day. A real time axis must keep them ordered and dated.
  const points: TokenPoint[] = [
    { day: '2026-07-01 23:00', delivered: 10, offered: 1 },
    { day: '2026-07-02 00:00', delivered: 20, offered: 2 },
    { day: '2026-07-02 01:00', delivered: 30, offered: 3 },
  ]
  const cols = { primary: '#111', secondary: '#222' }
  const bounds = { min: Date.UTC(2026, 6, 1, 23), max: Date.UTC(2026, 6, 2, 1) }

  it('builds a time axis spanning the given bounds', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const opt = tokensOption(points, cols, '1h', bounds) as any
    expect(opt.xAxis.type).toBe('time')
    expect(opt.xAxis.min).toBe(bounds.min)
    expect(opt.xAxis.max).toBe(bounds.max)
  })

  it('emits [epochMs, value] pairs in ascending time order', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const opt = tokensOption(points, cols, '1h', bounds) as any
    const delivered = opt.series[0].data as [number, number][]
    expect(delivered).toEqual([
      [Date.UTC(2026, 6, 1, 23), 10],
      [Date.UTC(2026, 6, 2, 0), 20],
      [Date.UTC(2026, 6, 2, 1), 30],
    ])
    const xs = delivered.map((d) => d[0])
    expect(xs).toEqual([...xs].sort((a, b) => a - b))
  })

  it('works without bounds (empty data)', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const opt = tokensOption([], cols, '1d') as any
    expect(opt.xAxis.type).toBe('time')
    expect(opt.xAxis.min).toBeUndefined()
    expect(opt.series[0].data).toEqual([])
  })
})

describe('catalogGrowthDomains', () => {
  it('returns the sorted union of catalog and delivered domains', () => {
    expect(catalogGrowthDomains(growth)).toEqual(['auth', 'ui'])
  })

  it('handles an empty bundle', () => {
    expect(catalogGrowthDomains({ catalog: [], delivered: [] })).toEqual([])
  })
})

describe('catalogGrowthOption', () => {
  const ms1 = Date.UTC(2026, 0, 1)
  const ms2 = Date.UTC(2026, 0, 2)

  it('aggregates across all domains when no domain is selected', () => {
    const opt = catalogGrowthOption(growth, colors, '1d')

    // Always exactly two series, regardless of domain count, on a time axis.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.series as any[]).length).toBe(2)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.xAxis as any).type).toBe('time')
    // x components are the UTC epoch ms of each day, ascending.
    expect(pairs(opt, 'All domains · catalog').map((d) => d[0])).toEqual([
      ms1,
      ms2,
    ])
    // Catalog summed per day across auth + ui.
    expect(values(opt, 'All domains · catalog')).toEqual([140, 180])
    // Delivered summed per day (auth on day 1, ui on day 2).
    expect(values(opt, 'All domains · delivered')).toEqual([30, 25])
  })

  it('restricts to a single domain when selected', () => {
    const opt = catalogGrowthOption(growth, colors, '1d', undefined, 'auth')

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.series as any[]).length).toBe(2)
    expect(values(opt, 'auth · catalog')).toEqual([100, 120])
    // auth was only delivered on day 1.
    expect(values(opt, 'auth · delivered')).toEqual([30, 0])
  })

  it('spans the given time bounds', () => {
    const bounds = { min: ms1, max: ms2 }
    const opt = catalogGrowthOption(growth, colors, '1d', bounds)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.xAxis as any).min).toBe(ms1)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.xAxis as any).max).toBe(ms2)
  })
})

import { versionAdoptionOption } from '@/views/metricsCharts'
import type { KitVersionAdoption } from '@/types/metrics'

describe('versionAdoptionOption', () => {
  const colors = {
    primary: '#1',
    info: '#2',
    success: '#3',
    warning: '#4',
    secondary: '#5',
    error: '#6',
  }

  const adoption: KitVersionAdoption = {
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
    buckets: [
      { day: '2026-01-01', counts: { v1: 3, v2: 0 } },
      { day: '2026-01-02', counts: { v1: 1, v2: 2 } },
    ],
  }

  it('builds one stacked area series per version', () => {
    const opt = versionAdoptionOption(adoption, colors, '1d')
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const series = opt.series as any[]
    expect(series.map((s) => s.name)).toEqual(['v1', 'v2'])
    expect(series.every((s) => s.stack === 'uses')).toBe(true)
    expect(series.every((s) => s.areaStyle)).toBeTruthy()
    // v2 counts across the two buckets (missing → 0).
    expect(series[1].data.map((d: [number, number]) => d[1])).toEqual([0, 2])
  })

  it('renders empty (no series) when there is no data', () => {
    const empty: KitVersionAdoption = {
      ...adoption,
      versions: [],
      buckets: [],
    }
    const opt = versionAdoptionOption(empty, colors, '1d')
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.series as any[]).length).toBe(0)
  })
})
