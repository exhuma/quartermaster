<script setup lang="ts">
import { onMounted } from 'vue'

import { useAuth } from '@/composables/useAuth'
import { useLoading } from '@/composables/useLoading'
import { authError, retryAuthentication } from '@/auth/reauthGuard'
import BuildMeta from '@/components/BuildMeta.vue'

const { isAuthenticated, displayName, refresh, login, logout } = useAuth()
const { isLoading } = useLoading()

onMounted(refresh)
</script>

<template>
  <v-app>
    <v-app-bar color="primary" flat>
      <v-app-bar-title>Instruction Kits</v-app-bar-title>
      <v-btn variant="text" :to="{ name: 'kits' }">Kits</v-btn>
      <v-btn variant="text" :to="{ name: 'integration' }">Integrate</v-btn>
      <v-btn variant="text" :to="{ name: 'mount' }">Mount</v-btn>
      <v-btn variant="text" :to="{ name: 'metrics' }">Metrics</v-btn>
      <v-spacer />
      <template v-if="isAuthenticated">
        <span class="mr-2 text-body-2">{{ displayName }}</span>
        <v-btn variant="text" prepend-icon="mdi-logout" @click="logout()">
          Sign out
        </v-btn>
      </template>
      <v-btn v-else variant="text" prepend-icon="mdi-login" @click="login()">
        Sign in
      </v-btn>

      <!-- Build identity (repo link + commit). Hidden when its build-time
           env vars are unset; low-visibility so it does not distract. -->
      <BuildMeta class="ml-2 build-meta-bar" />

      <!-- Page-level loading feedback anchored under the app bar. -->
      <v-progress-linear
        :active="isLoading"
        indeterminate
        color="primary"
        absolute
        location="bottom"
      />
    </v-app-bar>

    <v-main>
      <router-view />
    </v-main>

    <!-- Re-auth loop guard: shown when a fresh token is still rejected, so the
         user sees a clear error instead of an endless redirect loop. -->
    <v-dialog :model-value="authError !== null" persistent max-width="480">
      <v-card title="Authentication failed">
        <v-card-text>{{ authError }}</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="logout()">Sign out</v-btn>
          <v-btn color="primary" @click="retryAuthentication()">
            Sign in again
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-app>
</template>

<style scoped>
/* Low-visibility build-identity strip; full opacity on hover. */
.build-meta-bar {
  opacity: 0.55;
}
.build-meta-bar:hover {
  opacity: 1;
}
</style>
