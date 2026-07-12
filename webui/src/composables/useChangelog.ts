// Public changelog singleton. The changelog is served unauthenticated at
// GET /changelog.json (rendered from changelog.in by clproc), so it is fetched
// with a plain `fetch` — deliberately NOT through the `api` client, which
// forces the vendor Accept header and is oriented at authenticated /api calls.

import { ref } from 'vue'

import { apiBaseUrl } from '@/config'

// The shape clproc's JSON renderer emits (see app/changelog.py). Only the
// fields the UI uses are typed; unused keys (simple_version/full_version) are
// left off intentionally.
export interface ChangelogEntry {
  subject: string
  type: string
  detail: string
  is_highlight: boolean
  is_internal: boolean
  issue_ids: number[]
  issue_urls: string[]
}

export interface ChangelogRelease {
  logs: ChangelogEntry[]
  meta: {
    version: string
    // null for the not-yet-tagged (unreleased) group.
    date: string | null
    notes: string
  }
}

const releases = ref<ChangelogRelease[]>([])
const error = ref<string | null>(null)
const loaded = ref(false)

export function useChangelog() {
  async function fetchChangelog(): Promise<void> {
    error.value = null
    try {
      const resp = await fetch(`${apiBaseUrl}/changelog.json`, {
        headers: { Accept: 'application/json' },
      })
      if (!resp.ok) {
        throw new Error(`Failed to load changelog (HTTP ${resp.status})`)
      }
      releases.value = (await resp.json()) as ChangelogRelease[]
      loaded.value = true
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  return { releases, error, loaded, fetchChangelog }
}
