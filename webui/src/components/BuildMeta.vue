<script setup lang="ts">
// Build-identity strip (module-github-link, module-release-metadata).
// Reads the three build-time env vars itself and renders nothing when all
// are absent. Each element is hidden individually when its var is unset.
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    // Suppress the external DiceBear <img> fetch (air-gapped deployments
    // where outbound requests to api.dicebear.com are blocked).
    isolated?: boolean
  }>(),
  { isolated: false }
)

const repoUrl = computed(() => import.meta.env.VITE_GITHUB_REPO_URL ?? '')
const commit = computed(() => import.meta.env.VITE_APP_COMMIT ?? '')
const buildTime = computed(() => import.meta.env.VITE_APP_BUILD_TIME ?? '')
const version = computed(() => import.meta.env.VITE_APP_VERSION ?? '')

const shortCommit = computed(() => commit.value.slice(0, 7))
const identiconUrl = computed(() =>
  shortCommit.value
    ? `https://api.dicebear.com/9.x/identicon/svg?seed=${shortCommit.value}`
    : ''
)
const commitTooltip = computed(() =>
  buildTime.value ? `Built at — ${buildTime.value}` : 'Build'
)
const showIdenticon = computed(
  () => !props.isolated && shortCommit.value !== ''
)
const visible = computed(
  () => repoUrl.value !== '' || commit.value !== '' || version.value !== ''
)
</script>

<template>
  <div v-if="visible" class="build-meta">
    <v-btn
      v-if="repoUrl"
      :href="repoUrl"
      target="_blank"
      rel="noopener noreferrer"
      icon="mdi-github"
      variant="text"
      size="small"
      density="comfortable"
      aria-label="Source code"
      title="Source code"
    />
    <img
      v-if="showIdenticon"
      class="build-meta__identicon"
      :src="identiconUrl"
      alt=""
      width="20"
      height="20"
    />
    <v-chip
      v-if="version"
      size="x-small"
      label
      variant="outlined"
      class="build-meta__version"
    >
      {{ version }}
    </v-chip>
    <v-tooltip v-if="shortCommit" :text="commitTooltip" location="top">
      <template #activator="{ props: tip }">
        <v-chip v-bind="tip" size="x-small" label variant="outlined">
          {{ shortCommit }}
        </v-chip>
      </template>
    </v-tooltip>
  </div>
</template>

<style scoped>
.build-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.build-meta__identicon {
  border-radius: 4px;
}
</style>
