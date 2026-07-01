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
// per-domain catalog series.
export function palette(c: Colors): string[] {
  return [c.primary, c.info, c.success, c.warning, c.secondary, c.error]
}

const round = (n: number, dp = 1): number => Number(n.toFixed(dp))

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

export function catalogGrowthOption(
  g: CatalogGrowth,
  colors: string[]
): EChartsOption {
  const days = Array.from(
    new Set([
      ...g.catalog.map((p) => p.day),
      ...g.delivered.map((p) => p.day),
    ])
  ).sort()
  const catalogDomains = Array.from(
    new Set(g.catalog.map((p) => p.domain))
  ).sort()
  const deliveredDomains = Array.from(
    new Set(g.delivered.map((p) => p.domain))
  ).sort()

  const catalogFor = (domain: string): number[] =>
    days.map(
      (d) =>
        g.catalog.find((p) => p.day === d && p.domain === domain)
          ?.total_tokens ?? 0
    )
  const deliveredFor = (domain: string): number[] =>
    days.map(
      (d) =>
        g.delivered.find((p) => p.day === d && p.domain === domain)?.tokens ?? 0
    )

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const series: any[] = []
  catalogDomains.forEach((domain, i) => {
    series.push({
      name: `${domain} · catalog`,
      type: 'line',
      stack: 'catalog',
      areaStyle: { opacity: 0.18 },
      showSymbol: false,
      data: catalogFor(domain),
      itemStyle: { color: colors[i % colors.length] },
    })
  })
  deliveredDomains.forEach((domain, i) => {
    series.push({
      name: `${domain} · delivered`,
      type: 'line',
      lineStyle: { type: 'dashed' },
      showSymbol: false,
      data: deliveredFor(domain),
      itemStyle: { color: colors[i % colors.length] },
    })
  })

  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, type: 'scroll', textStyle: { fontSize: 10 } },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: days, boundaryGap: false },
    yAxis: { type: 'value', name: 'tokens' },
    series,
  }
}
