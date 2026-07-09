<script setup lang="ts">
// Public landing page: the pre-login pitch. Explains what Quartermaster is,
// the value it brings, how to connect a coding agent, and what you can do once
// connected. Works with or without a session — the calls-to-action and onward
// deep links adapt to `isAuthenticated`.
import { useAuth } from '@/composables/useAuth'

const { isAuthenticated, login } = useAuth()

// What Quartermaster is, in one card each. Kept short and jargon-light.
const values = [
  {
    icon: 'mdi-tune-variant',
    title: 'Per-task guidance',
    body: 'Your agent gets the right architecture and tooling advice for the task in front of it — matched as the work takes shape, not pinned once per project.',
  },
  {
    icon: 'mdi-shield-check',
    title: 'Never copied in',
    body: 'Kits load as extra context on demand. The files are never written into your repository, so your project stays clean.',
  },
  {
    icon: 'mdi-source-branch',
    title: 'Versioned & shared',
    body: 'One governed catalog your whole team draws from. Browse it, read any kit, or keep private kits only you can see.',
  },
  {
    icon: 'mdi-magnify',
    title: 'One entry point',
    body: 'Agents call a single tool, resolve_kits: describe the task, get back the right kits with their core guidance already inlined.',
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
  <v-container class="py-8">
    <!-- Hero: the whole pitch fits here without scrolling. Everything below is
         for readers who want more. -->
    <v-card variant="tonal" color="primary" class="pa-6 pa-md-8 mb-10">
      <h1 class="text-h4 text-md-h3 font-weight-medium mb-2">Quartermaster</h1>
      <p class="text-h6 text-medium-emphasis font-weight-regular mb-4">
        Versioned AI instruction kits, served to your coding agent on demand.
      </p>
      <p class="text-body-1 mb-6" style="max-width: 42rem">
        Quartermaster gives your coding agent the right guidance for whatever it
        is building — how to set up authentication, structure an API, wire a
        frontend — loaded as context for the task at hand and never copied into
        your project.
      </p>

      <div class="d-flex flex-wrap ga-3">
        <template v-if="isAuthenticated">
          <v-btn color="primary" size="large" :to="{ name: 'kits' }">
            Open catalog
          </v-btn>
          <v-btn
            variant="text"
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
            prepend-icon="mdi-login"
            @click="login('/catalog')"
          >
            Sign in
          </v-btn>
          <v-btn variant="text" size="large" href="#how-it-works">
            How it works
          </v-btn>
        </template>
      </div>
    </v-card>

    <!-- What it is / the value. -->
    <section class="mb-10">
      <h2 class="text-h5 font-weight-medium mb-1">Why teams use it</h2>
      <p class="text-medium-emphasis mb-4">
        Good instructions that reach your agent at the right moment — without
        cluttering every repository.
      </p>
      <v-row>
        <v-col
          v-for="value in values"
          :key="value.title"
          cols="12"
          sm="6"
          md="3"
        >
          <v-card variant="tonal" height="100%" class="pa-4">
            <v-icon :icon="value.icon" size="28" color="primary" class="mb-2" />
            <h3 class="text-subtitle-1 font-weight-medium mb-1">
              {{ value.title }}
            </h3>
            <p class="text-body-2 text-medium-emphasis">{{ value.body }}</p>
          </v-card>
        </v-col>
      </v-row>
    </section>

    <!-- How to integrate: the short version. -->
    <section id="how-it-works" class="mb-10">
      <h2 class="text-h5 font-weight-medium mb-1">
        Connect an agent in three steps
      </h2>
      <p class="text-medium-emphasis mb-4">
        Quartermaster speaks MCP — the open protocol coding agents use to load
        extra context. If your agent supports MCP, it can use Quartermaster.
      </p>
      <v-row>
        <v-col v-for="(step, i) in steps" :key="step.title" cols="12" md="4">
          <v-card variant="outlined" height="100%" class="pa-4">
            <div class="d-flex align-center mb-2">
              <v-avatar color="primary" size="28" class="mr-3 text-body-2">
                {{ i + 1 }}
              </v-avatar>
              <h3 class="text-subtitle-1 font-weight-medium">
                {{ step.title }}
              </h3>
            </div>
            <p class="text-body-2 text-medium-emphasis">{{ step.body }}</p>
          </v-card>
        </v-col>
      </v-row>

      <div v-if="isAuthenticated" class="d-flex flex-wrap ga-3 mt-4">
        <v-btn
          variant="text"
          prepend-icon="mdi-connection"
          :to="{ name: 'integration' }"
        >
          Full integration guide
        </v-btn>
        <v-btn
          variant="text"
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
        class="mt-4"
      >
        Sign in to get your personal MCP URL and copy-paste setup for each
        coding agent.
      </v-alert>
    </section>

    <!-- What you can do once connected. -->
    <section>
      <h2 class="text-h5 font-weight-medium mb-1">
        What you can do once connected
      </h2>
      <p class="text-medium-emphasis mb-4">
        Everything the web UI and MCP server offer, in one place.
      </p>
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
  </v-container>
</template>
