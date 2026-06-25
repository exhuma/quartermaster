// Global page-level loading state. A single pending counter drives the
// v-progress-linear anchored under the app bar (module-vue-vuetify:
// loading-feedback). Singleton: the ref lives at module scope.

import { computed, ref } from 'vue'

const pending = ref(0)

export function useLoading() {
  const isLoading = computed(() => pending.value > 0)

  async function withLoading<T>(work: Promise<T>): Promise<T> {
    pending.value++
    try {
      return await work
    } finally {
      pending.value--
    }
  }

  return { isLoading, withLoading }
}
