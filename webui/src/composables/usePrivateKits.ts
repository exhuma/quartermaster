// Private-kit state singleton. A private kit is a standalone kit visible only
// to its owner; these calls hit the owner-scoped /api/private-kits routes.
// Any authenticated user may manage their own private kits (ownership, not the
// editor role, is the gate), so this is available to consumers too.

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type { KitInfo } from '@/types/kit'

const kits = ref<KitInfo[]>([])
const error = ref<string | null>(null)

function skeletonApplicability(summary: string): Record<string, unknown> {
  const emptyTraits = {
    languages: [],
    frameworks: [],
    capabilities: [],
    contexts: [],
  }
  return {
    kit_type: 'module',
    summary,
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

export function usePrivateKits() {
  async function fetchPrivateKits(): Promise<void> {
    error.value = null
    try {
      kits.value = await api.get<KitInfo[]>('/api/private-kits')
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  async function createPrivateKit(
    name: string,
    summary: string
  ): Promise<void> {
    error.value = null
    try {
      await api.post('/api/private-kits', {
        name,
        applicability: skeletonApplicability(summary),
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
      await fetchPrivateKits()
    } catch (err) {
      error.value = messageOf(err)
      throw err
    }
  }

  async function deletePrivateKit(name: string): Promise<void> {
    error.value = null
    try {
      await api.delete(`/api/private-kits/${encodeURIComponent(name)}`)
      await fetchPrivateKits()
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  return {
    kits,
    error,
    fetchPrivateKits,
    createPrivateKit,
    deletePrivateKit,
  }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
