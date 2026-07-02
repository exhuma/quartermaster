// Pure ECharts option builders for the Metrics dashboard. Each takes the
// server bundle slice plus the active Vuetify theme colours and returns an
// EChartsOption — no component state, so they stay easy to reason about.

import type { EChartsOption } from 'echarts'

import type {
  CatalogGrowth,
  Heatmap,
  KitUsage,
  TokenPoint,
  ToolLatency,
} from '@/types/metrics'

type Colors = Record<string, string>

// A stable qualitative palette drawn from theme tokens, for pies and the
// catalog vs delivery lines.
export function palette(c: Colors): string[] {
  return [c.primary, c.info, c.success, c.warning, c.secondary, c.error]
}

const round = (n: number, dp = 1): number => Number(n.toFixed(dp))

// Keep time-series x-axis labels compact: hourly buckets arrive as
// "YYYY-MM-DD HH:00" — show just "HH:00" so 24 of them fit; daily buckets
// ("YYYY-MM-DD") are shown as-is. The full bucket stays in the axis tooltip.
const bucketAxisLabel = (value: string): string =>
  value.includes(' ') ? value.split(' ')[1] : value

export function kitUsageOption(usage: KitUsage[], c: Colors): EChartsOption {
  // Horizontal bars, busiest on top. The API sorts busiest-first; ECharts
  // category axes render bottom-up, so reverse to put the top kit at the top.
  const rows = [...usage].reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value', minInterval: 1, name: 'deliveries' },
    yAxis: { type: 'category', data: rows.map((r) => r.kit) },
    series: [
      {
        type: 'bar',
        data: rows.map((r) => r.deliveries),
        itemStyle: { color: c.primary },
        barMaxWidth: 22,
      },
    ],
  }
}

export function tokensOption(points: TokenPoint[], c: Colors): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Delivered', 'Offered (on-demand)'], top: 0 },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: points.map((p) => p.day),
      boundaryGap: false,
      axisLabel: { formatter: bucketAxisLabel },
    },
    yAxis: { type: 'value', name: 'tokens' },
    series: [
      {
        name: 'Delivered',
        type: 'line',
        smooth: true,
        areaStyle: { opacity: 0.22 },
        data: points.map((p) => p.delivered),
        itemStyle: { color: c.primary },
        lineStyle: { color: c.primary },
      },
      {
        name: 'Offered (on-demand)',
        type: 'line',
        smooth: true,
        data: points.map((p) => p.offered),
        itemStyle: { color: c.secondary },
        lineStyle: { color: c.secondary, type: 'dashed' },
      },
    ],
  }
}

export function heatmapOption(
  h: Heatmap,
  c: Colors,
  kind: 'structural' | 'behavioural'
): EChartsOption {
  const label = kind === 'structural' ? 'similarity' : 'travel together'
  return {
    tooltip: {
      position: 'top',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      formatter: (p: any) => {
        const [x, y, v] = p.value as [number, number, number]
        const pct = Math.round(v * 100)
        return `${h.kits[x]} + ${h.kits[y]}<br/>${label}: ${pct}%`
      },
    },
    grid: { left: 8, right: 8, top: 8, bottom: 64, containLabel: true },
    xAxis: {
      type: 'category',
      data: h.kits,
      axisLabel: { rotate: 45, fontSize: 10 },
    },
    yAxis: { type: 'category', data: h.kits, axisLabel: { fontSize: 10 } },
    visualMap: {
      min: 0,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: [c.surface, c.primary] },
    },
    series: [
      {
        type: 'heatmap',
        data: h.cells.map((cell) => [cell.x, cell.y, round(cell.value, 2)]),
      },
    ],
  }
}

export function pieOption(
  mix: Record<string, number>,
  colors: string[]
): EChartsOption {
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { fontSize: 10 } },
    color: colors,
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '44%'],
        data: Object.entries(mix).map(([name, value]) => ({ name, value })),
        label: { fontSize: 10 },
      },
    ],
  }
}

export function toolLatencyOption(
  rows: ToolLatency[],
  c: Colors
): EChartsOption {
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['p50 ms', 'p95 ms'], top: 0 },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r.tool),
      axisLabel: { rotate: 30, fontSize: 10 },
    },
    yAxis: { type: 'value', name: 'ms' },
    series: [
      {
        name: 'p50 ms',
        type: 'bar',
        data: rows.map((r) => round(r.p50_ms)),
        itemStyle: { color: c.primary },
      },
      {
        name: 'p95 ms',
        type: 'bar',
        data: rows.map((r) => round(r.p95_ms)),
        itemStyle: { color: c.warning },
      },
    ],
  }
}

// The set of domains present in a catalog-growth bundle (union of catalog and
// delivered rows), sorted — the source of truth for the view's domain dropdown.
export function catalogGrowthDomains(g: CatalogGrowth): string[] {
  return Array.from(
    new Set([
      ...g.catalog.map((p) => p.domain),
      ...g.delivered.map((p) => p.domain),
    ])
  ).sort()
}

// A real catalog has many domains; one catalog+delivered line pair per domain
// makes the legend and plot unreadable. So the view filters by a single domain
// (or aggregates all of them) and this builder always emits exactly two summed
// series: `selectedDomain === null` sums across every domain, otherwise it
// restricts to the chosen one.
export function catalogGrowthOption(
  g: CatalogGrowth,
  colors: string[],
  selectedDomain: string | null = null
): EChartsOption {
  const days = Array.from(
    new Set([...g.catalog.map((p) => p.day), ...g.delivered.map((p) => p.day)])
  ).sort()

  const inScope = (domain: string): boolean =>
    selectedDomain === null || domain === selectedDomain

  const catalogSeries = days.map((d) =>
    g.catalog
      .filter((p) => p.day === d && inScope(p.domain))
      .reduce((sum, p) => sum + p.total_tokens, 0)
  )
  const deliveredSeries = days.map((d) =>
    g.delivered
      .filter((p) => p.day === d && inScope(p.domain))
      .reduce((sum, p) => sum + p.tokens, 0)
  )

  const label = selectedDomain ?? 'All domains'
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const series: any[] = [
    {
      name: `${label} · catalog`,
      type: 'line',
      areaStyle: { opacity: 0.18 },
      showSymbol: false,
      data: catalogSeries,
      itemStyle: { color: colors[0] },
    },
    {
      name: `${label} · delivered`,
      type: 'line',
      lineStyle: { type: 'dashed' },
      showSymbol: false,
      data: deliveredSeries,
      itemStyle: { color: colors[1] },
    },
  ]

  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, type: 'scroll', textStyle: { fontSize: 10 } },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: days,
      boundaryGap: false,
      axisLabel: { formatter: bucketAxisLabel },
    },
    yAxis: { type: 'value', name: 'tokens' },
    series,
  }
}
