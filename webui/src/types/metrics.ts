// Types for the in-app Metrics dashboard payload
// (GET /api/metrics/overview). Mirrors app/routers/metrics.py::build_overview.

export type MetricsWindow = '24h' | '7d' | '30d'

// Time-series bucket size. '1h' is useful for watching the 24h window evolve
// live; '1d' is the long-view default.
export type MetricsGranularity = '1h' | '1d'

export interface MetricsMeta {
  window: MetricsWindow
  granularity: MetricsGranularity
  generated_at: number
  retention_days: number
  store_enabled: boolean
  // OTLP export state, for the UI badge: exporting | inert | failing |
  // configured | unknown. The dashboard never depends on OTEL being healthy.
  otel_status: string
}

export interface KitUsage {
  kit: string
  deliveries: number
  tokens: number
}

export interface TokenPoint {
  day: string
  delivered: number
  offered: number
  suppressed: number
}

export interface ResolveHealth {
  total_calls: number
  engine_mix: Record<string, number>
  confidence_mix: Record<string, number>
  coverage_p50: number
  coverage_p95: number
  broadening_rate: number
}

export interface ToolLatency {
  tool: string
  calls: number
  errors: number
  p50_ms: number
  p95_ms: number
}

export interface HeatCell {
  x: number
  y: number
  value: number
  count?: number
}

export interface Heatmap {
  kits: string[]
  cells: HeatCell[]
}

export interface CatalogPoint {
  day: string
  domain: string
  total_tokens: number
  always_load_tokens: number
}

export interface DeliveredPoint {
  day: string
  domain: string
  tokens: number
}

export interface CatalogGrowth {
  catalog: CatalogPoint[]
  delivered: DeliveredPoint[]
}

export interface MetricsOverview {
  meta: MetricsMeta
  kit_usage: KitUsage[]
  tokens_timeseries: TokenPoint[]
  resolve_health: ResolveHealth
  tool_latency: ToolLatency[]
  co_occurrence: Heatmap
  structural_overlap: Heatmap
  catalog_growth: CatalogGrowth
}

// Per-kit version-adoption payload (GET /api/kits/{name}/version-adoption).
// Mirrors app/routers/metrics.py::kit_version_adoption. Each bucket maps a UTC
// time label to per-version served counts; `versions` is the union across the
// window, oldest → newest.
export interface VersionAdoptionBucket {
  day: string
  counts: Record<string, number>
}

export interface KitVersionAdoption {
  meta: {
    kit: string
    window: MetricsWindow
    granularity: MetricsGranularity
    generated_at: number
    retention_days: number
    store_enabled: boolean
    available_versions: string[]
  }
  granularity: MetricsGranularity
  versions: string[]
  buckets: VersionAdoptionBucket[]
}
