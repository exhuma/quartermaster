import { describe, expect, it } from 'vitest'

import {
  catalogGrowthDomains,
  catalogGrowthOption,
} from '@/views/metricsCharts'
import type { CatalogGrowth } from '@/types/metrics'

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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const seriesData = (opt: any, name: string): number[] =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  opt.series.find((s: any) => s.name === name).data

const colors = ['#c0', '#c1', '#c2']

describe('catalogGrowthDomains', () => {
  it('returns the sorted union of catalog and delivered domains', () => {
    expect(catalogGrowthDomains(growth)).toEqual(['auth', 'ui'])
  })

  it('handles an empty bundle', () => {
    expect(catalogGrowthDomains({ catalog: [], delivered: [] })).toEqual([])
  })
})

describe('catalogGrowthOption', () => {
  it('aggregates across all domains when no domain is selected', () => {
    const opt = catalogGrowthOption(growth, colors)

    // Always exactly two series, regardless of domain count.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.series as any[]).length).toBe(2)
    // Days sorted ascending.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.xAxis as any).data).toEqual(['2026-01-01', '2026-01-02'])
    // Catalog summed per day across auth + ui.
    expect(seriesData(opt, 'All domains · catalog')).toEqual([140, 180])
    // Delivered summed per day (auth on day 1, ui on day 2).
    expect(seriesData(opt, 'All domains · delivered')).toEqual([30, 25])
  })

  it('restricts to a single domain when selected', () => {
    const opt = catalogGrowthOption(growth, colors, 'auth')

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((opt.series as any[]).length).toBe(2)
    expect(seriesData(opt, 'auth · catalog')).toEqual([100, 120])
    // auth was only delivered on day 1.
    expect(seriesData(opt, 'auth · delivered')).toEqual([30, 0])
  })
})
