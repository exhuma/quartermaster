// Pure ECharts option builders for the Metrics dashboard. Each takes the
// server bundle slice plus the active Vuetify theme colours and returns an
// EChartsOption — no component state, so they stay easy to reason about.

import type { EChartsOption } from 'echarts'

import type {
  CatalogGrowth,
  Heatmap,
  KitUsage,
  KitVersionAdoption,
  MetricsGranularity,
  TokenPoint,
  ToolLatency,
} from '@/types/metrics'

type Colors = Record<string, string>

// Epoch-ms window the time-series x-axis should span, so the chart always
// shows the selected timespan even where buckets are sparse or missing.
export interface TimeBounds {
  min: number
  max: number
}

// A stable qualitative palette drawn from theme tokens, for pies and the
// catalog vs delivery lines.
export function palette(c: Colors): string[] {
  return [c.primary, c.info, c.success, c.warning, c.secondary, c.error]
}

// ECharts' built-in chrome colours — axis labels, axis/tick lines, split
// gridlines, legend text, the visualMap gradient labels — are a fixed dark
// grey that disappears on a dark surface (legends read dark-on-dark). The
// builders theme the *data* (series colours) but not this chrome, so it must
// be sourced from the active Vuetify theme. Applied centrally in BaseChart so
// every chart — current and future — stays legible in light and dark mode
// without each builder repeating it. Existing per-element styles (formatter,
// rotate, fontSize) are preserved; only colour is layered in.
export function withChartTheme(
  option: EChartsOption,
  c: Colors
): EChartsOption {
  const text = c['on-surface']
  const muted = c['on-surface-variant'] ?? text
  const line = c.outline
  const split = c['outline-variant'] ?? line
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const decorateAxis = (axis: any): any => ({
    axisLine: { lineStyle: { color: line } },
    axisTick: { lineStyle: { color: line } },
    splitLine: { lineStyle: { color: split } },
    ...axis,
    axisLabel: { color: muted, ...(axis?.axisLabel ?? {}) },
    nameTextStyle: { color: muted, ...(axis?.nameTextStyle ?? {}) },
  })
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapAxis = (a: any): any =>
    Array.isArray(a) ? a.map(decorateAxis) : a ? decorateAxis(a) : a
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const decorateLegend = (l: any): any => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const one = (x: any) => ({ ...x, textStyle: { color: text, ...x?.textStyle } })
    return Array.isArray(l) ? l.map(one) : l ? one(l) : l
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const themed: any = { textStyle: { color: text }, ...option }
  if (option.xAxis) themed.xAxis = mapAxis(option.xAxis)
  if (option.yAxis) themed.yAxis = mapAxis(option.yAxis)
  if (option.legend) themed.legend = decorateLegend(option.legend)
  if (option.visualMap) {
    const vm = option.visualMap
    themed.visualMap = Array.isArray(vm)
      ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
        vm.map((x: any) => ({ textStyle: { color: muted }, ...x }))
      : { textStyle: { color: muted }, ...vm }
  }
  return themed as EChartsOption
}

const round = (n: number, dp = 1): number => Number(n.toFixed(dp))

// Server bucket labels are UTC strings: "YYYY-MM-DD" (daily) or
// "YYYY-MM-DD HH:00" (hourly). Parse to epoch ms via an explicit-UTC ISO string
// so the time axis is timezone-safe (never reinterpreted in the browser's tz).
export function bucketToEpochMs(label: string): number {
  const iso = label.includes(' ')
    ? `${label.replace(' ', 'T')}:00Z`
    : `${label}T00:00:00Z`
  return Date.parse(iso)
}

// Render an epoch-ms tick back in UTC so axis/tooltip labels read exactly like
// the server's buckets (no local-tz hour shift). Hourly shows the hour; daily
// shows just the date.
const UTC_DATE = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  month: 'short',
  day: '2-digit',
})
const UTC_TIME = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})
export function formatBucketUTC(
  ms: number,
  granularity: MetricsGranularity
): string {
  const date = UTC_DATE.format(ms)
  return granularity === '1h' ? `${date} ${UTC_TIME.format(ms)}` : date
}

// Shared axis-triggered tooltip for the time-series line charts: a UTC bucket
// header plus one "marker name: value" line per series.
const timeSeriesTooltip =
  (granularity: MetricsGranularity) =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (params: any): string => {
    const rows = params as Array<{
      axisValue: number
      marker: string
      seriesName: string
      value: [number, number]
    }>
    const header = formatBucketUTC(rows[0].axisValue, granularity)
    const lines = rows.map(
      (p) => `${p.marker}${p.seriesName}: ${p.value[1].toLocaleString()}`
    )
    return [header, ...lines].join('<br/>')
  }

// x-axis config shared by both time-series charts: a real time axis spanning
// the selected window (when bounds are given), labelled in UTC.
function timeAxis(
  granularity: MetricsGranularity,
  bounds?: TimeBounds
): EChartsOption['xAxis'] {
  return {
    type: 'time',
    min: bounds?.min,
    max: bounds?.max,
    axisLabel: { formatter: (v: number) => formatBucketUTC(v, granularity) },
  }
}

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

export function tokensOption(
  points: TokenPoint[],
  c: Colors,
  granularity: MetricsGranularity,
  bounds?: TimeBounds
): EChartsOption {
  return {
    tooltip: { trigger: 'axis', formatter: timeSeriesTooltip(granularity) },
    legend: {
      data: ['Delivered', 'Offered (on-demand)', 'Suppressed (dedup savings)'],
      top: 0,
    },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: timeAxis(granularity, bounds),
    yAxis: { type: 'value', name: 'tokens' },
    series: [
      {
        name: 'Delivered',
        type: 'line',
        smooth: true,
        areaStyle: { opacity: 0.22 },
        data: points.map((p) => [bucketToEpochMs(p.day), p.delivered]),
        itemStyle: { color: c.primary },
        lineStyle: { color: c.primary },
      },
      {
        name: 'Offered (on-demand)',
        type: 'line',
        smooth: true,
        data: points.map((p) => [bucketToEpochMs(p.day), p.offered]),
        itemStyle: { color: c.secondary },
        lineStyle: { color: c.secondary, type: 'dashed' },
      },
      {
        name: 'Suppressed (dedup savings)',
        type: 'line',
        smooth: true,
        data: points.map((p) => [bucketToEpochMs(p.day), p.suppressed]),
        itemStyle: { color: c.success },
        lineStyle: { color: c.success, type: 'dotted' },
      },
    ],
  }
}

export function versionAdoptionOption(
  adoption: KitVersionAdoption,
  c: Colors,
  granularity: MetricsGranularity,
  bounds?: TimeBounds
): EChartsOption {
  // One stacked line+area per major version, so the reader sees both each
  // version's absolute usage and how the mix shifts as a repo migrates.
  const pal = palette(c)
  const series = adoption.versions.map((version, i) => ({
    name: version,
    type: 'line' as const,
    stack: 'uses',
    smooth: true,
    areaStyle: { opacity: 0.22 },
    data: adoption.buckets.map((b) => [
      bucketToEpochMs(b.day),
      b.counts[version] ?? 0,
    ]),
    itemStyle: { color: pal[i % pal.length] },
    lineStyle: { color: pal[i % pal.length] },
  }))
  return {
    tooltip: { trigger: 'axis', formatter: timeSeriesTooltip(granularity) },
    legend: { data: adoption.versions, top: 0 },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: timeAxis(granularity, bounds),
    yAxis: { type: 'value', name: 'served', minInterval: 1 },
    series,
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
// restricts to the chosen one. Points are plotted on a real UTC time axis.
export function catalogGrowthOption(
  g: CatalogGrowth,
  colors: string[],
  granularity: MetricsGranularity,
  bounds?: TimeBounds,
  selectedDomain: string | null = null
): EChartsOption {
  const days = Array.from(
    new Set([...g.catalog.map((p) => p.day), ...g.delivered.map((p) => p.day)])
  ).sort()

  const inScope = (domain: string): boolean =>
    selectedDomain === null || domain === selectedDomain

  const catalogSeries: [number, number][] = days.map((d) => [
    bucketToEpochMs(d),
    g.catalog
      .filter((p) => p.day === d && inScope(p.domain))
      .reduce((sum, p) => sum + p.total_tokens, 0),
  ])
  const deliveredSeries: [number, number][] = days.map((d) => [
    bucketToEpochMs(d),
    g.delivered
      .filter((p) => p.day === d && inScope(p.domain))
      .reduce((sum, p) => sum + p.tokens, 0),
  ])

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
    tooltip: { trigger: 'axis', formatter: timeSeriesTooltip(granularity) },
    legend: { top: 0, type: 'scroll', textStyle: { fontSize: 10 } },
    grid: { left: 8, right: 16, top: 32, bottom: 8, containLabel: true },
    xAxis: timeAxis(granularity, bounds),
    yAxis: { type: 'value', name: 'tokens' },
    series,
  }
}
