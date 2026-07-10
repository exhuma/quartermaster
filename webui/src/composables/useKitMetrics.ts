// Per-kit version-adoption state. Unlike the dashboard's useMetrics singleton,
// this is scoped to a single kit detail view, so it returns fresh refs per call
// (only one KitDetailView is mounted at a time). No analysis lives here — the
// server aggregates the isolated kit_version_uses telemetry, the view renders.

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type {
  KitVersionAdoption,
  MetricsGranularity,
  MetricsWindow,
} from '@/types/metrics'
import { useLoading } from './useLoading'

const { withLoading } = useLoading()

export function useKitMetrics() {
  const adoption = ref<KitVersionAdoption | null>(null)
  const error = ref<string | null>(null)

  async function fetchAdoption(
    name: string,
    window: MetricsWindow = '30d',
    granularity: MetricsGranularity = '1d'
  ): Promise<void> {
    error.value = null
    try {
      adoption.value = await withLoading(
        api.get<KitVersionAdoption>(
          `/api/kits/${encodeURIComponent(name)}/version-adoption` +
            `?window=${window}&granularity=${granularity}`
        )
      )
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  return { adoption, error, fetchAdoption }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
