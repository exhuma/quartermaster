// Kit catalog state singleton. Lists and mutates kits through the central
// api module; no business logic lives here (that is the server's job).

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type { KitInfo } from '@/types/kit'
import { useLoading } from './useLoading'

const kits = ref<KitInfo[]>([])
const error = ref<string | null>(null)

const { withLoading } = useLoading()

// A minimal, valid applicability manifest for a freshly-created kit. The
// full applicability/section editing lives in the kit editor.
function skeletonApplicability(): Record<string, unknown> {
  const emptyTraits = {
    languages: [],
    frameworks: [],
    capabilities: [],
    contexts: [],
  }
  return {
    kit_type: 'module',
    summary: 'New kit — edit applicability.',
    domains: [],
    languages: [],
    frameworks: [],
    contexts: [],
    requires: emptyTraits,
    excludes: emptyTraits,
    optional_signals: [],
    related_kits: [],
    priority: 50,
  }
}

export function useKits() {
  async function fetchKits(): Promise<void> {
    error.value = null
    try {
      kits.value = await withLoading(api.get<KitInfo[]>('/api/kits'))
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  async function createKit(name: string, summary: string): Promise<void> {
    error.value = null
    try {
      await withLoading(
        api.post('/api/kits', {
          name,
          applicability: { ...skeletonApplicability(), summary },
          summary,
          sections: [
            {
              file: 'invariant.md',
              title: 'Invariants',
              gloss: 'Core invariants for this kit.',
              always_load: true,
              body: `# ${name}\n\nDescribe the invariants here.\n`,
            },
          ],
        })
      )
      await fetchKits()
    } catch (err) {
      error.value = messageOf(err)
      throw err
    }
  }

  async function deleteKit(name: string): Promise<void> {
    error.value = null
    try {
      await withLoading(api.delete(`/api/kits/${encodeURIComponent(name)}`))
      await fetchKits()
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  return { kits, error, fetchKits, createKit, deleteKit }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
