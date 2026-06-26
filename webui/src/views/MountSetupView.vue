<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { useAppTokens } from '@/composables/useAppTokens'
import { useIntegration } from '@/composables/useIntegration'
import type { MintedToken } from '@/types/kit'

const { info, fetchInfo } = useIntegration()
const { tokens, fetchTokens, mint, revoke } = useAppTokens()

const davUrl = computed(() =>
  info.value
    ? `${info.value.server_origin}/dav`
    : `${window.location.origin}/dav`
)
const davsUrl = computed(() => davUrl.value.replace(/^https/, 'davs'))

const mintOpen = ref(false)
const newLabel = ref('')
const minted = ref<MintedToken | null>(null)

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

onMounted(async () => {
  await fetchInfo()
  await fetchTokens()
})

async function copy(text: string): Promise<void> {
  await navigator.clipboard.writeText(text)
}

async function submitMint(): Promise<void> {
  minted.value = await mint(newLabel.value)
  newLabel.value = ''
  mintOpen.value = false
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

    <v-card class="mb-6" title="App tokens">
      <v-card-text>
        <p class="mb-3">
          WebDAV mounts authenticate with HTTP Basic — use any username and an
          app token as the password. Mint one here; it is shown once.
        </p>

        <v-alert v-if="minted" type="success" variant="tonal" class="mb-3">
          <div class="mb-1 font-weight-medium">
            New token (copy it now — it won't be shown again):
          </div>
          <div class="d-flex align-center">
            <code class="text-body-2">{{ minted.token }}</code>
            <v-spacer />
            <v-btn
              size="small"
              variant="text"
              prepend-icon="mdi-content-copy"
              @click="copy(minted.token)"
            >
              Copy
            </v-btn>
          </div>
        </v-alert>

        <v-list v-if="tokens.length" density="compact">
          <v-list-item
            v-for="t in tokens"
            :key="t.id"
            :title="t.label || '(no label)'"
            :subtitle="`${t.id} · ${t.created}`"
          >
            <template #append>
              <v-btn
                icon="mdi-delete-outline"
                size="small"
                variant="text"
                color="error"
                @click="revoke(t.id)"
              />
            </template>
          </v-list-item>
        </v-list>
        <p v-else class="text-medium-emphasis">No app tokens yet.</p>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn color="primary" prepend-icon="mdi-plus" @click="mintOpen = true">
          New token
        </v-btn>
      </v-card-actions>
    </v-card>

    <v-card title="Mount instructions">
      <v-expansion-panels>
        <v-expansion-panel v-for="s in steps" :key="s.os" :title="s.os">
          <template #text>
            <pre class="snippet">{{ s.body }}</pre>
          </template>
        </v-expansion-panel>
      </v-expansion-panels>
    </v-card>

    <v-dialog v-model="mintOpen" max-width="420">
      <v-card title="New app token">
        <v-card-text>
          <v-text-field v-model="newLabel" label="Label (optional)" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="mintOpen = false">Cancel</v-btn>
          <v-btn color="primary" @click="submitMint">Mint</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
.snippet {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, monospace;
  font-size: 0.85rem;
}
</style>
