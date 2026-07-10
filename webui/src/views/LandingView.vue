<script setup lang="ts">
// Public landing page: the pre-login pitch, styled in the "Tactical
// Provisioning System" design language (bento grid of equipment-cased cards,
// mono serial numbers, brass accents). Explains what Quartermaster is, the
// value it brings, how to connect a coding agent, and what you can do once
// connected. Works with or without a session — the calls-to-action and onward
// deep links adapt to `isAuthenticated`.
import { useAuth } from '@/composables/useAuth'
import TacticalCard from '@/components/TacticalCard.vue'
import SectionHeader from '@/components/SectionHeader.vue'

const { isAuthenticated, login } = useAuth()

// Real, self-hosted repo year for the footer notice (no hard-coded year).
const year = new Date().getFullYear()

// What Quartermaster is, one equipment-cased card each. `cols` drives the
// asymmetric bento layout; `serial` is the decorative stamped code.
const values = [
  {
    icon: 'mdi-tune-variant',
    title: 'Per-task guidance',
    body: 'Your agent gets the right architecture and tooling advice for the task in front of it — matched as the work takes shape, not pinned once per project.',
    serial: 'QM-ARC-001',
    cols: 7,
  },
  {
    icon: 'mdi-shield-check',
    title: 'Never copied in',
    body: 'Kits load as extra context on demand. The files are never written into your repository, so your project stays clean.',
    serial: 'QM-SEC-042',
    cols: 5,
  },
  {
    icon: 'mdi-source-branch',
    title: 'Versioned & shared',
    body: 'One governed catalog your whole team draws from. Browse it, read any kit, or keep private kits only you can see.',
    serial: 'QM-CAT-108',
    cols: 5,
  },
  {
    icon: 'mdi-magnify',
    title: 'One entry point',
    body: 'Agents call a single tool, resolve_kits: describe the task, get back the right kits with their core guidance already inlined.',
    serial: 'QM-INT-777',
    cols: 7,
  },
]

// Three steps to connect a coding agent. The detail lives on the Integrate and
// Mount pages (auth-gated); this is the map, not the full guide.
const steps = [
  {
    title: 'Point your agent at the MCP server',
    body: 'Add the server URL to your coding agent — VS Code, Claude Code, opencode, or Copilot.',
  },
  {
    title: 'Sign in once',
    body: 'Authenticate through your Keycloak login, or use a long-lived app token for clients that cannot sign in through a browser.',
  },
  {
    title: 'Let it call resolve_kits',
    body: 'From then on your agent pulls the right kits for each task automatically — no manual copying, no stale instructions.',
  },
]

// How the server turns a free-text task into the right kits. Real behaviour,
// paired with the mono handshake snippet on the right.
const protocol = [
  {
    icon: 'mdi-brain',
    title: 'Trait inference',
    body: 'The server maps your task onto its trait vocabulary — via the connecting client’s own model, local embeddings, or a lexical floor — then ranks the matching kits.',
  },
  {
    icon: 'mdi-history',
    title: 'Versioning built in',
    body: 'Kits are semantically versioned, so agents always load instructions that match the version they are working against.',
  },
]

// An illustrative MCP handshake — documentation example, not live data.
const handshakeLines = [
  {
    prompt: true,
    text: 'mcp add quartermaster https://<your-server>/kits/mcp',
  },
  { tag: 'OK', text: 'Remote MCP server detected.' },
  {
    tag: 'DISCOVERY',
    text: 'Tools exposed: resolve_kits, get_kit, list_kits…',
  },
  { tag: 'READY', text: 'Instruction kits ready on demand.' },
]

// What the tool unlocks once connected. Each deep-links into the app for
// signed-in users; the routes are auth-gated, so the links show only then.
const capabilities = [
  {
    icon: 'mdi-magnify',
    text: 'Resolve the right kits for each task',
    to: { name: 'integration' },
  },
  {
    icon: 'mdi-book-open-variant',
    text: 'Browse and read the shared catalog',
    to: { name: 'kits' },
  },
  {
    icon: 'mdi-lock',
    text: 'Keep private kits only you can see',
    to: { name: 'private-kits' },
  },
  {
    icon: 'mdi-folder-network',
    text: 'Author kits by mounting the catalog as a drive',
    to: { name: 'mount' },
  },
  {
    icon: 'mdi-chart-line',
    text: 'See how kits are used across your team',
    to: { name: 'metrics' },
  },
]
</script>

<template>
  <div class="landing">
    <!-- Hero: the whole pitch fits here without scrolling. -->
    <section class="hero text-center px-4 py-12 py-md-16">
      <div class="hero__inner mx-auto">
        <span class="hero__badge qm-label">
          <span class="hero__badge-dot" />
          Self-hosted MCP server
        </span>
        <h1 class="hero__title font-weight-bold mt-6 mb-4">
          Provision your agents with
          <span class="text-primary">Precision.</span>
        </h1>
        <p class="hero__lede text-body-1 text-on-surface-variant mx-auto mb-8">
          Quartermaster is a self-hosted MCP server that serves versioned AI
          instruction kits to your coding agent — architecture preferences,
          tooling choices, and hard-won conventions, loaded for the task at hand
          and never copied into your project.
        </p>

        <div class="d-flex flex-wrap ga-3 justify-center">
          <template v-if="isAuthenticated">
            <v-btn
              color="primary"
              size="large"
              class="qm-glow font-weight-bold"
              :to="{ name: 'kits' }"
            >
              Open catalog
            </v-btn>
            <v-btn
              variant="outlined"
              color="primary"
              size="large"
              prepend-icon="mdi-connection"
              :to="{ name: 'integration' }"
            >
              Connect an agent
            </v-btn>
          </template>
          <template v-else>
            <v-btn
              color="primary"
              size="large"
              class="qm-glow font-weight-bold"
              prepend-icon="mdi-login"
              @click="login('/catalog')"
            >
              Sign in
            </v-btn>
            <v-btn
              variant="outlined"
              color="primary"
              size="large"
              href="#how-it-works"
            >
              How it works
            </v-btn>
          </template>
        </div>

        <!-- Tactical visual anchor. Placeholder for now: a brass-lit crate
             motif. TODO: swap for a final brand render dropped in src/assets. -->
        <div class="hero__visual mt-12 mx-auto" aria-hidden="true">
          <v-icon
            icon="mdi-package-variant-closed"
            size="120"
            color="primary"
            class="hero__crate"
          />
        </div>
      </div>
    </section>

    <v-container class="py-8">
      <!-- Bento grid: what it is / the value. -->
      <SectionHeader
        title="Why teams use it"
        subtitle="Good instructions that reach your agent at the right moment — without cluttering every repository."
        tag="CAPABILITY_ROOT"
      />
      <v-row class="mb-12">
        <v-col
          v-for="value in values"
          :key="value.title"
          cols="12"
          :md="value.cols"
        >
          <TacticalCard :serial="value.serial" class="pa-6 h-100">
            <v-icon
              :icon="value.icon"
              size="34"
              color="primary"
              class="mb-3 d-block"
            />
            <h3 class="text-h6 text-primary font-weight-bold mb-2">
              {{ value.title }}
            </h3>
            <p class="text-body-2 text-on-surface-variant mb-0">
              {{ value.body }}
            </p>
          </TacticalCard>
        </v-col>
      </v-row>

      <!-- How to integrate: the short version. -->
      <section id="how-it-works">
        <SectionHeader
          title="Connect an agent in three steps"
          subtitle="Quartermaster speaks MCP — the open protocol coding agents use to load extra context. If your agent supports MCP, it can use Quartermaster."
          tag="ONBOARD_SEQ"
        />
        <v-row>
          <v-col v-for="(step, i) in steps" :key="step.title" cols="12" md="4">
            <TacticalCard :serial="`STEP-0${i + 1}`" class="pa-6 h-100">
              <div class="d-flex align-center mb-3 ga-3">
                <v-avatar
                  color="primary"
                  size="34"
                  class="font-weight-bold text-body-1"
                >
                  {{ i + 1 }}
                </v-avatar>
                <h3 class="text-subtitle-1 font-weight-bold">
                  {{ step.title }}
                </h3>
              </div>
              <p class="text-body-2 text-on-surface-variant mb-0">
                {{ step.body }}
              </p>
            </TacticalCard>
          </v-col>
        </v-row>

        <div v-if="isAuthenticated" class="d-flex flex-wrap ga-3 mt-6">
          <v-btn
            variant="text"
            color="primary"
            prepend-icon="mdi-connection"
            :to="{ name: 'integration' }"
          >
            Full integration guide
          </v-btn>
          <v-btn
            variant="text"
            color="primary"
            prepend-icon="mdi-folder-network"
            :to="{ name: 'mount' }"
          >
            Author kits
          </v-btn>
        </div>
        <v-alert
          v-else
          type="info"
          variant="tonal"
          density="comfortable"
          class="mt-6"
        >
          Sign in to get your personal MCP URL and copy-paste setup for each
          coding agent.
        </v-alert>
      </section>

      <!-- The protocol, spelled out, with an illustrative handshake. -->
      <section class="mt-12">
        <SectionHeader
          title="The power of Model Context Protocol"
          subtitle="MCP lets AI assistants discover and call tools a server exposes. Quartermaster publishes its kit catalog as MCP tools, so context arrives exactly when the agent needs it."
          tag="PROTOCOL"
        />
        <v-row align="center">
          <v-col cols="12" md="6">
            <div
              v-for="item in protocol"
              :key="item.title"
              class="d-flex ga-4 mb-6"
            >
              <v-avatar
                color="surface-container-high"
                rounded="lg"
                size="48"
                class="flex-shrink-0"
              >
                <v-icon :icon="item.icon" color="primary" />
              </v-avatar>
              <div>
                <h4 class="text-subtitle-1 font-weight-bold mb-1">
                  {{ item.title }}
                </h4>
                <p class="text-body-2 text-on-surface-variant mb-0">
                  {{ item.body }}
                </p>
              </div>
            </div>
          </v-col>
          <v-col cols="12" md="6">
            <TacticalCard :hover="false" class="pa-5">
              <div
                class="qm-label text-on-surface-variant mb-3 d-flex align-center ga-2"
              >
                <v-icon icon="mdi-console" size="16" />
                MCP handshake
              </div>
              <pre class="handshake font-mono text-body-2 mb-0"><template
                v-for="(line, i) in handshakeLines"
                :key="i"
              ><span v-if="line.prompt" class="text-on-surface-variant">$ </span><span
                  v-else
                  class="text-on-surface-variant"
                >[{{ line.tag }}] </span><span
                  :class="line.prompt ? 'text-primary' : 'text-on-surface'"
                >{{ line.text }}</span>
</template></pre>
            </TacticalCard>
          </v-col>
        </v-row>
      </section>

      <!-- What you can do once connected. -->
      <section class="mt-12">
        <SectionHeader
          title="What you can do once connected"
          subtitle="Everything the web UI and MCP server offer, in one place."
          tag="MANIFEST"
        />
        <v-list lines="one" class="bg-transparent">
          <v-list-item
            v-for="cap in capabilities"
            :key="cap.text"
            :prepend-icon="cap.icon"
            :title="cap.text"
            :to="isAuthenticated ? cap.to : undefined"
          />
        </v-list>
      </section>

      <!-- Closing call to action. -->
      <section class="text-center py-12">
        <h2 class="text-h4 font-weight-bold mb-4">
          Ready for <span class="text-primary">deployment?</span>
        </h2>
        <p class="text-body-1 text-on-surface-variant mx-auto mb-8 cta__lede">
          Point your agent at Quartermaster and start provisioning it with the
          expertise it deserves.
        </p>
        <div class="d-flex flex-wrap ga-3 justify-center">
          <v-btn
            v-if="!isAuthenticated"
            color="primary"
            size="large"
            class="qm-glow font-weight-bold"
            prepend-icon="mdi-login"
            @click="login('/catalog')"
          >
            Sign in
          </v-btn>
          <v-btn
            v-else
            color="primary"
            size="large"
            class="qm-glow font-weight-bold"
            :to="{ name: 'kits' }"
          >
            Open catalog
          </v-btn>
          <v-btn
            variant="outlined"
            color="primary"
            size="large"
            href="#how-it-works"
          >
            How it works
          </v-btn>
        </div>
      </section>

      <!-- Footer strip. -->
      <footer
        class="landing__footer d-flex flex-wrap align-center justify-space-between ga-4 pt-6"
      >
        <span class="qm-label text-primary">Quartermaster Tactical</span>
        <span class="text-caption text-on-surface-variant">
          © {{ year }} Quartermaster · Tailored kit distribution for your
          agents.
        </span>
      </footer>
    </v-container>
  </div>
</template>

<style scoped>
/* Hero eyebrow badge: a pulsing brass dot inside an outlined pill. */
.hero__badge {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.9rem;
  font-size: 0.72rem;
  border-radius: 9999px;
  border: 1px solid rgb(var(--v-theme-outline-variant));
  background-color: rgb(var(--v-theme-surface-container));
  color: rgb(var(--v-theme-on-surface-variant));
}
.hero__badge-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 9999px;
  background-color: rgb(var(--v-theme-primary));
  box-shadow: 0 0 8px rgb(var(--v-theme-primary));
}

.hero__inner {
  max-width: 56rem;
}
.hero__title {
  font-size: clamp(2.25rem, 5vw, 3rem);
  line-height: 1.1;
  letter-spacing: -0.02em;
}
.hero__lede {
  max-width: 42rem;
}

/* Placeholder crate visual: a soft radial brass glow behind the icon. */
.hero__visual {
  position: relative;
  width: 100%;
  max-width: 40rem;
  height: 14rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: radial-gradient(
    circle at center,
    rgba(233, 193, 118, 0.12),
    transparent 68%
  );
}
.hero__crate {
  filter: drop-shadow(0 18px 40px rgba(233, 193, 118, 0.25));
}

.handshake {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}

.cta__lede {
  max-width: 38rem;
}

.landing__footer {
  border-top: 1px solid rgb(var(--v-theme-outline-variant));
}
</style>
