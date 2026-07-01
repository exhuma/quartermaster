// Metrics dashboard state singleton. Fetches the aggregated overview bundle
// from the OTEL-independent local store via the central api module; no
// analysis logic lives here (the server aggregates, the view renders).

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type {
  MetricsGranularity,
  MetricsOverview,
  MetricsWindow,
} from '@/types/metrics'
import { useLoading } from './useLoading'

const overview = ref<MetricsOverview | null>(null)
const error = ref<string | null>(null)
const window = ref<MetricsWindow>('7d')
const granularity = ref<MetricsGranularity>('1d')

const { withLoading } = useLoading()

// The 24h window is watched live, so it defaults to hourly buckets; the wider
// windows default to daily. Switching windows resets to this default, which the
// user can then override with the granularity toggle.
function defaultGranularity(w: MetricsWindow): MetricsGranularity {
  return w === '24h' ? '1h' : '1d'
}

export function useMetrics() {
  async function fetchMetrics(): Promise<void> {
    error.value = null
    try {
      overview.value = await withLoading(
        api.get<MetricsOverview>(
          `/api/metrics/overview?window=${window.value}&granularity=${granularity.value}`
        )
      )
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  async function setWindow(next: MetricsWindow): Promise<void> {
    if (next === window.value) {
      return
    }
    window.value = next
    granularity.value = defaultGranularity(next)
    await fetchMetrics()
  }

  async function setGranularity(next: MetricsGranularity): Promise<void> {
    if (next === granularity.value) {
      return
    }
    granularity.value = next
    await fetchMetrics()
  }

  return {
    overview,
    error,
    window,
    granularity,
    fetchMetrics,
    setWindow,
    setGranularity,
  }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
