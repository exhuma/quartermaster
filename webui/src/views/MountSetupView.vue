<script setup lang="ts">
import { computed, onMounted } from 'vue'

import AppTokensCard from '@/components/AppTokensCard.vue'
import { useIntegration } from '@/composables/useIntegration'

const { info, fetchInfo } = useIntegration()

const davUrl = computed(() =>
  info.value
    ? `${info.value.server_origin}/dav`
    : `${window.location.origin}/dav`
)
const davsUrl = computed(() => davUrl.value.replace(/^https/, 'davs'))

const steps = computed(() => [
  {
    os: 'macOS (Finder)',
    body:
      `Finder → Go → Connect to Server → ${davUrl.value}\n` +
      `Username: any · Password: your app token`,
  },
  {
    os: 'Windows (Explorer)',
    body:
      `Explorer → Map network drive → ${davUrl.value}\n` +
      `Use your app token as the password (TLS is required).`,
  },
  {
    os: 'Linux (GNOME Files)',
    body:
      `Files → Other Locations → ${davsUrl.value}\n` +
      `or: mount -t davfs ${davUrl.value} /mnt/kits`,
  },
  {
    os: 'Any OS (rclone)',
    body:
      `rclone config  # WebDAV remote, vendor=other, url=${davUrl.value}\n` +
      `rclone mount kits: /mnt/kits --vfs-cache-mode writes`,
  },
])

onMounted(fetchInfo)

async function copy(text: string): Promise<void> {
  await navigator.clipboard.writeText(text)
}
</script>

<template>
  <v-container>
    <h1 class="text-h5 font-weight-medium mb-1">Mount kits locally</h1>
    <p class="text-medium-emphasis mb-4">
      Mount the catalog as a drive and author kits with a coding agent. Changes
      are visible to the MCP immediately — no restart.
    </p>

    <v-card class="mb-6" variant="tonal" color="primary">
      <v-card-text class="d-flex align-center">
        <div>
          <div class="text-caption text-medium-emphasis">WebDAV endpoint</div>
          <code class="text-body-1">{{ davUrl }}</code>
        </div>
        <v-spacer />
        <v-btn
          variant="text"
          prepend-icon="mdi-content-copy"
          @click="copy(davUrl)"
        >
          Copy
        </v-btn>
      </v-card-text>
    </v-card>

    <app-tokens-card />

    <v-card title="Mount instructions">
      <v-expansion-panels>
        <v-expansion-panel v-for="s in steps" :key="s.os" :title="s.os">
          <template #text>
            <pre class="snippet">{{ s.body }}</pre>
          </template>
        </v-expansion-panel>
      </v-expansion-panels>
    </v-card>
  </v-container>
</template>

<style scoped>
.snippet {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.85rem;
}
</style>
