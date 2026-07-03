<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useAppTokens } from '@/composables/useAppTokens'
import type { MintedToken } from '@/types/kit'

const { tokens, fetchTokens, mint, revoke } = useAppTokens()

const mintOpen = ref(false)
const newLabel = ref('')
const minted = ref<MintedToken | null>(null)

onMounted(fetchTokens)

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
  <v-card class="mb-6" title="App tokens">
    <v-card-text>
      <p class="mb-3">
        Long-lived tokens for clients that can't refresh OAuth — WebDAV mounts
        (the HTTP Basic password) and MCP clients such as opencode (sent as
        <code>Authorization: Bearer &lt;token&gt;</code>). Each token is bound
        to your account, shown once, and revocable here.
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
  </v-card>
</template>
