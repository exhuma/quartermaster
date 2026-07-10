<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AppTokensCard from '@/components/AppTokensCard.vue'
import { useIntegration } from '@/composables/useIntegration'

// Canonical hook scripts — imported verbatim so what we show is exactly what
// ships (single source of truth; the same files are dogfooded via
// .claude/settings.json and exercised by server/tests/test_claude_code_hooks.py).
import promptReminder from '@/docs/claude-code/qm-prompt-reminder.sh?raw'
import editReminder from '@/docs/claude-code/qm-edit-reminder.sh?raw'
import recordResolve from '@/docs/claude-code/qm-record-resolve.sh?raw'
import claudeSettings from '@/docs/claude-code/settings.json?raw'

const { info, error, fetchInfo, registerUserAgent } = useIntegration()

const tab = ref('vscode')
const agentTab = ref('opencode')

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

// A strongly-worded trigger list for agents that only support static rule
// files (no programmable hooks). Drop it into the agent's rules file so the
// re-resolve behavior is at least stated as forcefully as possible.
const rulesTriggerList = `## Quartermaster — resolve_kits is a STANDING behavior

Call mcp__quartermaster__resolve_kits(task="…") not once, but AGAIN whenever:
- I ask you to make or plan a change;
- you start a new subsystem, feature, or aspect;
- the direction shifts or new traits appear (e.g. "add login" becoming OIDC);
- you resume editing after a context compaction.

Do NOT edit files for a new aspect of the work without first (re-)resolving.
Load kit sections lean via get_kit(name, sections=[…]).`

// opencode plugin: best-effort nudge on local edit tools. opencode has NO
// prompt-submit hook, and MCP tool calls may not trigger tool hooks
// (sst/opencode#2319), so pair this with the rules trigger list above.
const opencodePlugin = `// ~/.config/opencode/plugin/quartermaster-reminder.js
// opencode exposes tool.execute.before/after + session/tui events, but has NO
// first-class prompt-submit hook, and MCP tool calls may not reliably trigger
// tool hooks (sst/opencode#2319). Treat this as a best-effort nudge and rely
// on a strong AGENTS.md trigger list (see the "Rules-only agents" panel).
export const QuartermasterReminder = async () => {
  const EDIT_TOOLS = new Set(["edit", "write", "patch"])
  return {
    "tool.execute.before": async (input) => {
      if (EDIT_TOOLS.has(input.tool)) {
        console.error(
          "[Quartermaster] call resolve_kits(task=…) before editing; " +
          "re-resolve on scope/direction changes."
        )
      }
    },
  }
}`

// Cursor hooks (>= 1.7). beforeSubmitPrompt injects context each prompt.
// Field names evolve — check https://cursor.com/docs/hooks for the current shape.
const cursorHooks = `// .cursor/hooks.json
{
  "version": 1,
  "hooks": {
    "beforeSubmitPrompt": [
      { "command": "./.cursor/hooks/qm-reminder.sh" }
    ]
  }
}
// .cursor/hooks/qm-reminder.sh  (chmod +x)
//   #!/usr/bin/env bash
//   # stdin is a JSON hook payload; emit context back on stdout.
//   jq -cn --arg m "Call mcp_quartermaster_resolve_kits before editing; \\
//   re-resolve on scope/direction changes." '{ "additionalContext": $m }'`

// Cline hooks (>= v3.36, macOS/Linux). PreToolUse gets JSON on stdin and
// returns JSON on stdout. Docs: https://docs.cline.bot .
const clineHooks = `# .clinerules/hooks/pre-tool-use.sh  (chmod +x)
#!/usr/bin/env bash
# Cline passes a JSON payload on stdin describing the pending tool call and
# returns JSON on stdout. Inject a resolve_kits reminder as extra context.
set -euo pipefail
input=$(cat)
jq -cn --arg m "Before editing, call mcp__quartermaster__resolve_kits(task=…); \\
re-resolve when the work changes shape." '{ "additionalContext": $m }'`

// Windsurf Cascade Hooks. Event/matcher names vary by version — verify at
// https://docs.windsurf.com/windsurf/cascade/hooks .
const windsurfHooks = `// .windsurf/hooks.json
{
  "hooks": {
    "preToolUse": [
      {
        "matcher": "edit_file|write_to_file",
        "command": ".windsurf/hooks/qm-reminder.sh"
      }
    ]
  }
}`

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

    <v-divider class="my-8" />

    <section>
      <h2 class="text-h6 font-weight-medium mb-1">
        Keeping <code>resolve_kits</code> alive — harness enforcement
      </h2>
      <p class="text-medium-emphasis mb-4">
        <code>resolve_kits</code> is meant to be re-called throughout a session,
        not once at the start. Wire your agent's harness to keep nudging it.
      </p>

      <v-alert type="warning" variant="tonal" class="mb-6">
        <div class="font-weight-medium mb-1">The adoption problem</div>
        Static <code>AGENTS.md</code> / <code>CLAUDE.md</code> guidance is
        loaded once and then <strong>decays</strong> over a long session —
        agents reliably resolve at the start and drift off it as the work moves
        on. <code>resolve_kits</code> needs to be
        <strong>re-called mid-task</strong>
        (new subsystem, direction shift, after a context compaction). Don't rely
        on model discretion; enforce it in the harness.
      </v-alert>

      <!-- Claude Code: full working reference. -->
      <v-card class="mb-6" title="Claude Code hooks">
        <v-card-text>
          <p class="mb-4">
            Three small hooks reproduce the pattern: a per-prompt reminder, a
            non-blocking pre-edit nudge that stays silent once you've resolved
            this session, and a recorder that flips that switch. Drop the
            scripts in <code>.claude/hooks/</code> (<code>chmod +x</code>) and
            the config in <code>.claude/settings.json</code>.
          </p>

          <div class="d-flex align-center mb-1">
            <div class="text-subtitle-2">
              <code>.claude/settings.json</code>
            </div>
            <v-spacer />
            <v-btn
              size="small"
              variant="text"
              prepend-icon="mdi-content-copy"
              @click="copy(claudeSettings)"
            >
              Copy
            </v-btn>
          </div>
          <pre class="snippet mb-4">{{ claudeSettings }}</pre>

          <div class="d-flex align-center mb-1">
            <div class="text-subtitle-2">
              <code>.claude/hooks/qm-prompt-reminder.sh</code>
              <span class="text-medium-emphasis">— UserPromptSubmit</span>
            </div>
            <v-spacer />
            <v-btn
              size="small"
              variant="text"
              prepend-icon="mdi-content-copy"
              @click="copy(promptReminder)"
            >
              Copy
            </v-btn>
          </div>
          <pre class="snippet mb-4">{{ promptReminder }}</pre>

          <div class="d-flex align-center mb-1">
            <div class="text-subtitle-2">
              <code>.claude/hooks/qm-edit-reminder.sh</code>
              <span class="text-medium-emphasis"
                >— PreToolUse (non-blocking)</span
              >
            </div>
            <v-spacer />
            <v-btn
              size="small"
              variant="text"
              prepend-icon="mdi-content-copy"
              @click="copy(editReminder)"
            >
              Copy
            </v-btn>
          </div>
          <pre class="snippet mb-4">{{ editReminder }}</pre>

          <div class="d-flex align-center mb-1">
            <div class="text-subtitle-2">
              <code>.claude/hooks/qm-record-resolve.sh</code>
              <span class="text-medium-emphasis">— PostToolUse</span>
            </div>
            <v-spacer />
            <v-btn
              size="small"
              variant="text"
              prepend-icon="mdi-content-copy"
              @click="copy(recordResolve)"
            >
              Copy
            </v-btn>
          </div>
          <pre class="snippet mb-4">{{ recordResolve }}</pre>

          <p class="mb-2">
            <strong>Two output shapes.</strong> For
            <code>UserPromptSubmit</code>, whatever the hook prints to stdout is
            injected into the model's context for that turn as
            <em>plain text</em> — no JSON envelope. For <code>PreToolUse</code>,
            emit a JSON object to add context without blocking the edit:
          </p>
          <pre class="snippet mb-4">
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"…"}}</pre
          >
          <p class="mb-4">
            Omitting <code>permissionDecision</code> keeps it non-blocking — the
            edit proceeds and the text is added as context. The per-session
            state key comes from <code>session_id</code> on the hook's stdin
            (read with <code>jq</code>); state is written under
            <code>$XDG_CACHE_HOME/quartermaster/sessions/</code> so it's outside
            the repo and never committed.
          </p>

          <v-alert type="info" variant="tonal" density="comfortable">
            <code>.claude/</code> is often gitignored. Decide deliberately
            whether to commit these hooks: commit them for team-wide
            enforcement, or keep them local (and gitignore any project-local
            state dir you choose instead of the XDG cache).
          </v-alert>
        </v-card-text>
      </v-card>

      <!-- Other agents: research-backed, one panel each. -->
      <v-card class="mb-6" title="Other coding agents">
        <v-card-text>
          <p class="text-medium-emphasis mb-4">
            Hook/event support as of mid-2026. Schemas evolve — verify field
            names against each tool's current docs.
          </p>
          <v-tabs v-model="agentTab" color="primary" show-arrows>
            <v-tab value="opencode">opencode</v-tab>
            <v-tab value="cursor">Cursor</v-tab>
            <v-tab value="cline">Cline</v-tab>
            <v-tab value="windsurf">Windsurf</v-tab>
            <v-tab value="rules">Rules-only</v-tab>
          </v-tabs>
          <v-tabs-window v-model="agentTab" class="mt-4">
            <v-tabs-window-item value="opencode">
              <p class="mb-3">
                <strong>Has hooks (with caveats).</strong> opencode's plugin API
                exposes <code>tool.execute.before</code>/<code>.after</code>
                plus session/TUI events, but <em>no</em> first-class
                prompt-submit hook, and MCP tool calls may not reliably trigger
                tool hooks (sst/opencode#2319). Best-effort nudge on local edit
                tools; pair it with the rules trigger list.
              </p>
              <pre class="snippet">{{ opencodePlugin }}</pre>
            </v-tabs-window-item>
            <v-tabs-window-item value="cursor">
              <p class="mb-3">
                <strong>Has hooks (≥ 1.7).</strong>
                <code>beforeSubmitPrompt</code> injects context each prompt;
                <code>afterFileEdit</code>, <code>preToolUse</code>/<code
                  >postToolUse</code
                >
                and <code>beforeMCPExecution</code> are also available (JSON on
                stdin/stdout).
              </p>
              <pre class="snippet">{{ cursorHooks }}</pre>
            </v-tabs-window-item>
            <v-tabs-window-item value="cline">
              <p class="mb-3">
                <strong>Has hooks (≥ v3.36, macOS/Linux).</strong>
                <code>PreToolUse</code> gets JSON on stdin and returns JSON on
                stdout; place scripts in <code>.clinerules/hooks/</code>.
              </p>
              <pre class="snippet">{{ clineHooks }}</pre>
            </v-tabs-window-item>
            <v-tabs-window-item value="windsurf">
              <p class="mb-3">
                <strong>Has hooks.</strong> Cascade Hooks
                (<code>.windsurf/hooks.json</code>) run pre/post agent actions.
              </p>
              <pre class="snippet">{{ windsurfHooks }}</pre>
            </v-tabs-window-item>
            <v-tabs-window-item value="rules">
              <p class="mb-3">
                <strong
                  >Rules only — no programmable pre-edit/pre-prompt hooks
                  today:</strong
                >
                <em>Continue</em> (rules files), <em>Aider</em> (<code
                  >CONVENTIONS.md</code
                >
                / read files), and <em>Zed</em> (static <code>.rules</code>;
                agent lifecycle hooks are still open feature requests). You
                can't force a re-resolve, so state it as forcefully as possible
                in the rules file:
              </p>
              <pre class="snippet">{{ rulesTriggerList }}</pre>
            </v-tabs-window-item>
          </v-tabs-window>
        </v-card-text>
      </v-card>

      <!-- Verification. -->
      <v-card title="How to verify it works">
        <v-card-text>
          <p class="mb-2">
            Unit-test the hook scripts by piping sample payloads through them —
            the Claude Code reference scripts ship with such a test
            (<code>server/tests/test_claude_code_hooks.py</code>,
            <code>uv&nbsp;run&nbsp;pytest</code>). Assert the four behaviors:
          </p>
          <ul class="mb-3 ps-6">
            <li>
              <strong>Nudge before resolve:</strong> a fresh
              <code>session_id</code> through the PreToolUse hook emits valid
              <code>additionalContext</code> JSON mentioning
              <code>resolve_kits</code>.
            </li>
            <li>
              <strong>Silent after resolve:</strong> run the record hook for
              that session, then the PreToolUse hook prints nothing.
            </li>
            <li>
              <strong>Re-nudge in a new session:</strong> a different
              <code>session_id</code> nudges again.
            </li>
            <li>
              <strong>Valid JSON:</strong> every emitted payload parses, and
              <code>settings.json</code> wires all three matchers.
            </li>
          </ul>
          <pre class="snippet">
echo '{"session_id":"s1"}' | ./.claude/hooks/qm-edit-reminder.sh   # nudges (JSON)
echo '{"session_id":"s1"}' | ./.claude/hooks/qm-record-resolve.sh  # record resolve
echo '{"session_id":"s1"}' | ./.claude/hooks/qm-edit-reminder.sh   # silent
echo '{"session_id":"s2"}' | ./.claude/hooks/qm-edit-reminder.sh   # nudges again</pre
          >
        </v-card-text>
      </v-card>
    </section>
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
