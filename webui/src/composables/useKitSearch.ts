// Free-text search over the kit catalog (metadata + instruction content).
// Complements useKits' plain listing; no business logic lives here (that
// is the server's job — see GET /api/search).

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type { KitSearchResponse, KitSearchResult } from '@/types/kit'
import { useLoading } from './useLoading'

const results = ref<KitSearchResult[]>([])
const error = ref<string | null>(null)

const { withLoading } = useLoading()

export function useKitSearch() {
  async function search(query: string, limit = 20): Promise<void> {
    error.value = null
    try {
      const response = await withLoading(
        api.get<KitSearchResponse>(
          `/api/search?q=${encodeURIComponent(query)}&limit=${limit}`
        )
      )
      results.value = response.results
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  function clear(): void {
    results.value = []
    error.value = null
  }

  return { results, error, search, clear }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
