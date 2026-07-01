// Current-user role singleton. The server is the source of truth for the
// caller's role (the token may not carry it), so the SPA fetches /api/me and
// gates editing controls on the result. `isEditor` folds to false until the
// first successful fetch, so controls stay hidden rather than flashing.

import { computed, ref } from 'vue'

import { api, ApiError } from '@/api'

export interface Me {
  sub: string
  label: string
  role: 'editor' | 'consumer'
}

const me = ref<Me | null>(null)
const error = ref<string | null>(null)

export function useMe() {
  const isEditor = computed(() => me.value?.role === 'editor')

  async function fetchMe(): Promise<void> {
    error.value = null
    try {
      me.value = await api.get<Me>('/api/me')
    } catch (err) {
      // On failure the role is unknown — fall back to non-editor rather than
      // leaving a stale role that could reveal editor controls.
      me.value = null
      error.value =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err)
    }
  }

  return { me, error, isEditor, fetchMe }
}
