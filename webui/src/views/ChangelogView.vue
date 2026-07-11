<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  useChangelog,
  type ChangelogEntry,
  type ChangelogRelease,
} from '@/composables/useChangelog'

const { releases, error, loaded, fetchChangelog } = useChangelog()

onMounted(fetchChangelog)

// --- Audience ("[MCP]" / "[UI]" / ...) ------------------------------------
// Each entry's subject is authored with a leading audience marker (see
// changelog.in). We surface it as a filterable chip and strip it from the
// displayed subject.
interface Audience {
  key: string
  label: string
  color: string
}

const AUDIENCES: Audience[] = [
  { key: 'MCP', label: 'MCP', color: 'primary' },
  { key: 'UI', label: 'Web UI', color: 'info' },
  { key: 'API', label: 'REST API', color: 'secondary' },
  { key: 'Ops', label: 'Ops', color: 'warning' },
  { key: 'Security', label: 'Security', color: 'error' },
]

const AUDIENCE_BY_KEY = new Map(AUDIENCES.map((a) => [a.key, a]))

function audienceOf(entry: ChangelogEntry): Audience | null {
  const match = entry.subject.match(/^\[([^\]]+)\]/)
  return (match && AUDIENCE_BY_KEY.get(match[1])) || null
}

function subjectText(entry: ChangelogEntry): string {
  return entry.subject.replace(/^\[[^\]]+\]\s*/, '')
}

// Only offer filters for audiences actually present in the data.
const availableAudiences = computed<Audience[]>(() => {
  const present = new Set<string>()
  for (const release of releases.value) {
    for (const entry of release.logs) {
      const a = audienceOf(entry)
      if (a) present.add(a.key)
    }
  }
  return AUDIENCES.filter((a) => present.has(a.key))
})

// `null` = show everything.
const selectedAudience = ref<string | null>(null)

function visibleEntries(release: ChangelogRelease): ChangelogEntry[] {
  return release.logs.filter((entry) => {
    if (entry.is_internal) return false
    if (!selectedAudience.value) return true
    return audienceOf(entry)?.key === selectedAudience.value
  })
}

// Releases with at least one visible entry under the current filter.
const visibleReleases = computed(() =>
  releases.value
    .map((release) => ({ release, entries: visibleEntries(release) }))
    .filter((r) => r.entries.length > 0)
)

// --- Rendering helpers -----------------------------------------------------
function releaseTitle(release: ChangelogRelease): string {
  // A null date marks the not-yet-tagged group.
  return release.meta.date ? release.meta.version : 'Unreleased'
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(`${iso}T00:00:00Z`)
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

// Minimal, safe inline-markdown renderer for the `detail` prose: escape all
// HTML first, then re-introduce only `code`, **bold**, and [text](http…)
// links. Content is maintainer-authored (changelog.in), and escaping-first
// means even raw HTML in the source cannot inject markup.
function inlineMarkdown(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    )
}
</script>

<template>
  <v-container class="changelog py-8" style="max-width: 900px">
    <header class="mb-6">
      <span class="qm-label text-primary">Changelog</span>
      <h1 class="text-h4 font-weight-bold mt-2 mb-2">What's changed</h1>
      <p class="text-body-1 text-on-surface-variant mb-0">
        Behaviour visible to MCP clients and to users of this web UI, newest
        first. Filter by the surface a change touches.
      </p>
    </header>

    <!-- Audience filter -->
    <div
      v-if="availableAudiences.length"
      class="mb-6 d-flex align-center flex-wrap ga-2"
    >
      <v-chip
        :variant="selectedAudience === null ? 'flat' : 'tonal'"
        :color="selectedAudience === null ? 'primary' : undefined"
        size="small"
        @click="selectedAudience = null"
      >
        All
      </v-chip>
      <v-chip
        v-for="a in availableAudiences"
        :key="a.key"
        :variant="selectedAudience === a.key ? 'flat' : 'tonal'"
        :color="a.color"
        size="small"
        @click="selectedAudience = a.key"
      >
        {{ a.label }}
      </v-chip>
    </div>

    <!-- Error -->
    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      {{ error }}
    </v-alert>

    <!-- Loading -->
    <div v-else-if="!loaded" class="py-8 text-center">
      <v-progress-circular indeterminate color="primary" />
    </div>

    <!-- Empty -->
    <v-alert
      v-else-if="visibleReleases.length === 0"
      type="info"
      variant="tonal"
    >
      No changelog entries to show.
    </v-alert>

    <!-- Releases -->
    <template v-else>
      <section
        v-for="{ release, entries } in visibleReleases"
        :key="release.meta.version"
        class="release mb-8"
      >
        <div class="d-flex align-baseline ga-3 mb-3">
          <h2 class="text-h6 font-weight-bold mb-0">
            {{ releaseTitle(release) }}
          </h2>
          <span
            v-if="release.meta.date"
            class="text-caption text-on-surface-variant font-mono"
          >
            {{ formatDate(release.meta.date) }}
          </span>
          <v-chip v-else size="x-small" color="primary" variant="tonal" label>
            in development
          </v-chip>
        </div>

        <p
          v-if="release.meta.notes.trim()"
          class="text-body-2 text-on-surface-variant mb-4"
        >
          {{ release.meta.notes.trim() }}
        </p>

        <v-card variant="tonal" class="release-card">
          <v-list lines="two" bg-color="transparent">
            <v-list-item
              v-for="(entry, i) in entries"
              :key="i"
              :class="{ 'entry--highlight': entry.is_highlight }"
            >
              <template #prepend>
                <v-chip
                  v-if="audienceOf(entry)"
                  :color="audienceOf(entry)!.color"
                  size="x-small"
                  label
                  class="mr-3 audience-chip"
                >
                  {{ audienceOf(entry)!.label }}
                </v-chip>
              </template>

              <v-list-item-title class="text-wrap font-weight-medium">
                <v-icon
                  v-if="entry.is_highlight"
                  icon="mdi-star"
                  size="x-small"
                  color="primary"
                  class="mr-1"
                />
                {{ subjectText(entry) }}
                <v-chip
                  size="x-small"
                  variant="outlined"
                  class="ml-2 type-chip"
                  label
                >
                  {{ entry.type }}
                </v-chip>
              </v-list-item-title>

              <v-list-item-subtitle
                v-if="entry.detail"
                class="text-wrap mt-1 detail"
              >
                <!-- eslint-disable-next-line vue/no-v-html -->
                <span v-html="inlineMarkdown(entry.detail)" />
              </v-list-item-subtitle>

              <div v-if="entry.issue_urls.length" class="mt-1">
                <a
                  v-for="(url, j) in entry.issue_urls"
                  :key="url"
                  :href="url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-caption mr-2"
                >
                  #{{ entry.issue_ids[j] }}
                </a>
              </div>
            </v-list-item>
          </v-list>
        </v-card>
      </section>
    </template>
  </v-container>
</template>

<style scoped>
.qm-label {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.75rem;
}

.audience-chip {
  min-width: 4.5rem;
  justify-content: center;
}

.type-chip {
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.7;
}

/* Highlighted (important MCP-behaviour) entries get a brass left rule. */
.entry--highlight {
  border-left: 2px solid rgb(var(--v-theme-primary));
}

.detail :deep(code) {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.85em;
  background: rgba(var(--v-theme-on-surface), 0.08);
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
}
</style>
