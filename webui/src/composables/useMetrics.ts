// Metrics dashboard state singleton. Fetches the aggregated overview bundle
// from the OTEL-independent local store via the central api module; no
// analysis logic lives here (the server aggregates, the view renders).

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type { MetricsOverview, MetricsWindow } from '@/types/metrics'
import { useLoading } from './useLoading'

const overview = ref<MetricsOverview | null>(null)
const error = ref<string | null>(null)
const window = ref<MetricsWindow>('7d')

const { withLoading } = useLoading()

export function useMetrics() {
  async function fetchMetrics(): Promise<void> {
    error.value = null
    try {
      overview.value = await withLoading(
        api.get<MetricsOverview>(
          `/api/metrics/overview?window=${window.value}`
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
    await fetchMetrics()
  }

  return { overview, error, window, fetchMetrics, setWindow }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
