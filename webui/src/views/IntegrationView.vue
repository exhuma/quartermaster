<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppTokensCard from '@/components/AppTokensCard.vue'
import { useIntegration } from '@/composables/useIntegration'

const { info, error, fetchInfo, registerUserAgent } = useIntegration()

const tab = ref('vscode')

const mcpUrl = computed(() => info.value?.mcp_url ?? '')

const vscodeSnippet = computed(
  () => `// .vscode/mcp.json
{
  "servers": {
    "instructions": {
      "type": "http",
      "url": "${mcpUrl.value}"
    }
  }
}
// VS Code discovers Keycloak via the server's OAuth well-known docs
// and runs a browser PKCE sign-in automatically.`
)

const claudeSnippet = computed(
  () => `claude mcp add --transport http instructions ${mcpUrl.value}
# Authenticate via the browser OAuth flow when prompted.`
)

const opencodeSnippet = computed(
  () => `// ~/.config/opencode/opencode.jsonc
//
// RECOMMENDED for opencode: a long-lived token. opencode's OAuth refresh is
// unreliable, so the OIDC flow below drops the connection once the access
// token expires. Mint a token in "App tokens" below and send it as a static
// Authorization header — it never needs refreshing:
{
  "mcp": {
    "instructions": {
      "type": "remote",
      "url": "${mcpUrl.value}",
      "headers": { "Authorization": "Bearer <your-app-token>" }
    }
  }
}
//
// --- OR, the OAuth flow (may need periodic re-auth) ---
// {
//   "mcp": {
//     "instructions": {
//       "type": "remote",
//       "url": "${mcpUrl.value}",
//       "oauth": { "clientId": "<public-keycloak-client-id>" }
//     }
//   }
// }
// Use a PUBLIC Keycloak client (NO secret): Client authentication OFF,
// Standard flow ON, PKCE S256. A confidential client fails the token
// exchange with invalid_client.
// Register opencode's callback as a Valid redirect URI:
//   http://127.0.0.1:19876/mcp/oauth/callback
// Then authenticate:  opencode mcp auth instructions`
)

const copilotSnippet = computed(
  () => `# Send fixed headers instead of a bearer token:
X-Client-Id: <your-keycloak-client-id>
X-Client-Secret: <your-keycloak-client-secret>
# Endpoint: ${mcpUrl.value}`
)

const genericSnippet = computed(
  () => `POST ${mcpUrl.value}
Authorization: Bearer <token>
# Streamable-HTTP MCP transport. The bearer token may be either a
# short-lived Keycloak access token or a long-lived app token minted in
# "App tokens" below (ideal for clients that can't refresh OAuth).`
)

const regUserAgent = ref('')
const regLabel = ref('')
const regStatus = ref<'idle' | 'ok' | 'error'>('idle')
const regMessage = ref('')

onMounted(fetchInfo)

async function copy(text: string): Promise<void> {
  await navigator.clipboard.writeText(text)
}

async function submitRegister(): Promise<void> {
  regStatus.value = 'idle'
  try {
    await registerUserAgent(regUserAgent.value, regLabel.value)
    regStatus.value = 'ok'
    regMessage.value = `Registered "${regUserAgent.value}".`
    regUserAgent.value = ''
    regLabel.value = ''
  } catch (err) {
    regStatus.value = 'error'
    regMessage.value = err instanceof Error ? err.message : String(err)
  }
}
</script>

<template>
  <v-container>
    <h1 class="text-h5 font-weight-medium mb-1">Connect a coding agent</h1>
    <p class="text-medium-emphasis mb-4">
      Load instruction kits on demand over MCP. Authentication uses your
      Keycloak realm.
    </p>

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      class="mb-4"
      :text="error"
    />

    <template v-if="info">
      <v-card class="mb-6" variant="tonal" color="primary">
        <v-card-text class="d-flex align-center">
          <div>
            <div class="text-caption text-medium-emphasis">MCP endpoint</div>
            <code class="text-body-1">{{ info.mcp_url }}</code>
          </div>
          <v-spacer />
          <v-btn
            variant="text"
            prepend-icon="mdi-content-copy"
            @click="copy(info.mcp_url)"
          >
            Copy
          </v-btn>
        </v-card-text>
      </v-card>

      <v-card class="mb-6">
        <v-tabs v-model="tab" color="primary">
          <v-tab value="vscode">VS Code</v-tab>
          <v-tab value="claude">Claude Code</v-tab>
          <v-tab value="opencode">opencode</v-tab>
          <v-tab v-if="info.copilot_auth_enabled" value="copilot">
            Copilot
          </v-tab>
          <v-tab value="generic">Generic</v-tab>
        </v-tabs>
        <v-card-text>
          <v-tabs-window v-model="tab">
            <v-tabs-window-item value="vscode">
              <pre class="snippet">{{ vscodeSnippet }}</pre>
            </v-tabs-window-item>
            <v-tabs-window-item value="claude">
              <pre class="snippet">{{ claudeSnippet }}</pre>
            </v-tabs-window-item>
            <v-tabs-window-item value="opencode">
              <pre class="snippet">{{ opencodeSnippet }}</pre>
            </v-tabs-window-item>
            <v-tabs-window-item value="copilot">
              <pre class="snippet">{{ copilotSnippet }}</pre>
            </v-tabs-window-item>
            <v-tabs-window-item value="generic">
              <pre class="snippet">{{ genericSnippet }}</pre>
            </v-tabs-window-item>
          </v-tabs-window>
        </v-card-text>
      </v-card>

      <app-tokens-card />

      <v-row>
        <v-col cols="12" md="6">
          <v-card class="h-100" title="Authentication">
            <v-card-text>
              <v-list density="compact" lines="two">
                <v-list-item
                  title="Keycloak realm"
                  :subtitle="info.keycloak_realm"
                />
                <v-list-item title="Issuer" :subtitle="info.keycloak_issuer" />
                <v-list-item
                  title="Scopes"
                  :subtitle="info.oauth_scopes.join(' ')"
                />
                <v-list-item
                  title="OAuth discovery"
                  :subtitle="info.oauth_metadata_url"
                />
              </v-list>
            </v-card-text>
          </v-card>
        </v-col>

        <v-col cols="12" md="6">
          <v-card class="h-100" title="REST API access">
            <v-card-text>
              <p class="mb-3">
                Direct REST clients must send
                <code>Accept: {{ info.api_media_type }}</code> and register
                their <code>User-Agent</code> below. Browsers and MCP clients
                are exempt.
              </p>
              <v-text-field
                v-model="regUserAgent"
                label="User-Agent"
                placeholder="my-agent/1.0"
                density="comfortable"
              />
              <v-text-field
                v-model="regLabel"
                label="Label (optional)"
                density="comfortable"
              />
              <v-alert
                v-if="regStatus !== 'idle'"
                :type="regStatus === 'ok' ? 'success' : 'error'"
                variant="tonal"
                class="mb-3"
                :text="regMessage"
              />
              <v-btn
                color="primary"
                :disabled="!regUserAgent"
                @click="submitRegister"
              >
                Register client
              </v-btn>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
    </template>
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
