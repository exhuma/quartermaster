<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { userManager } from '@/auth/oidc'
import { useAuth } from '@/composables/useAuth'

const router = useRouter()
const { refresh } = useAuth()
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    const user = await userManager.signinRedirectCallback()
    await refresh()
    const returnTo =
      typeof user.state === 'string' && user.state ? user.state : '/'
    await router.replace(returnTo)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
})
</script>

<template>
  <v-container
    class="d-flex justify-center align-center"
    style="min-height: 60vh"
  >
    <v-alert v-if="error" type="error" variant="tonal" max-width="480">
      <div class="text-subtitle-1 mb-1">Sign-in failed</div>
      {{ error }}
    </v-alert>
    <div v-else class="text-center">
      <v-progress-circular indeterminate color="primary" />
      <div class="mt-3 text-medium-emphasis">Completing sign-in…</div>
    </div>
  </v-container>
</template>
