<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { useKits } from '@/composables/useKits'
import { useKitSearch } from '@/composables/useKitSearch'
import { useMe } from '@/composables/useMe'
import SectionHeader from '@/components/SectionHeader.vue'
import StatusChip from '@/components/StatusChip.vue'
import type { KitInfo, KitSearchSectionMatch } from '@/types/kit'

const { kits, error, fetchKits, createKit, deleteKit } = useKits()
const {
  results: searchResults,
  error: searchError,
  search: searchKits,
  clear: clearSearch,
} = useKitSearch()
const { isEditor, fetchMe } = useMe()

const headers = [
  { title: 'Name', key: 'name' },
  { title: 'Layer', key: 'source_layer' },
  { title: 'Summary', key: 'description' },
  { title: 'Latest', key: 'latest_version' },
  { title: 'Versions', key: 'versions' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const createOpen = ref(false)
const newName = ref('')
const newSummary = ref('')
const createError = ref<string | null>(null)

const deleteTarget = ref<string | null>(null)

const nameRule = (v: string) =>
  /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(v) ||
  'Lowercase words joined by hyphens, e.g. module-auth-oidc'

onMounted(() => {
  fetchKits()
  fetchMe()
})

// --- Search kits and instructions --------------------------------------

const searchQuery = ref('')
const expanded = ref<string[]>([])
let debounceHandle: ReturnType<typeof setTimeout> | undefined

const searchActive = computed(() => searchQuery.value.trim().length >= 2)

interface DisplayKit extends KitInfo {
  matchedFields?: string[]
  matchedSections?: KitSearchSectionMatch[]
}

// While a search is active, drive the table from search results instead of
// the plain catalog list — enriched with the full KitInfo row (layer,
// versions, editable) so the columns render the same either way.
const displayedKits = computed<DisplayKit[]>(() => {
  if (!searchActive.value) {
    return kits.value
  }
  const byName = new Map(kits.value.map((k) => [k.name, k]))
  return searchResults.value.map((r) => {
    const base = byName.get(r.name)
    return {
      name: r.name,
      description: r.summary,
      versions: base?.versions ?? [r.version],
      latest_version: base?.latest_version ?? r.version,
      source_layer: base?.source_layer ?? null,
      editable: base?.editable ?? false,
      broken: base?.broken ?? false,
      error: base?.error ?? null,
      matchedFields: r.matched_fields,
      matchedSections: r.sections,
    }
  })
})

watch(searchQuery, (value) => {
  if (debounceHandle) {
    clearTimeout(debounceHandle)
  }
  const query = value.trim()
  if (query.length < 2) {
    expanded.value = []
    clearSearch()
    return
  }
  debounceHandle = setTimeout(() => {
    void searchKits(query)
  }, 300)
})

async function submitCreate(): Promise<void> {
  createError.value = null
  try {
    await createKit(newName.value, newSummary.value)
    createOpen.value = false
    newName.value = ''
    newSummary.value = ''
  } catch (err) {
    createError.value = err instanceof Error ? err.message : String(err)
  }
}

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value) {
    await deleteKit(deleteTarget.value)
  }
  deleteTarget.value = null
}
</script>

<template>
  <v-container>
    <SectionHeader
      title="Instruction kits"
      subtitle="The shared catalog your agents draw from. Open a kit to read its sections, versions, and applicability."
      tag="KIT_INVENTORY"
    />
    <div class="d-flex align-center mb-4">
      <v-spacer />
      <v-btn
        v-if="isEditor"
        color="primary"
        prepend-icon="mdi-plus"
        @click="createOpen = true"
      >
        New kit
      </v-btn>
      <v-chip v-else size="small" variant="tonal" color="info">
        Read-only — editor role required to modify kits
      </v-chip>
    </div>

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      class="mb-4"
      :text="error"
    />
    <v-alert
      v-if="searchError"
      type="error"
      variant="tonal"
      class="mb-4"
      :text="searchError"
    />

    <v-text-field
      v-model="searchQuery"
      label="Search kits and instructions"
      prepend-inner-icon="mdi-magnify"
      density="compact"
      clearable
      class="mb-4"
      hide-details
    />

    <v-card>
      <v-data-table
        :headers="headers"
        :items="displayedKits"
        item-value="name"
        :show-expand="searchActive"
        v-model:expanded="expanded"
        :row-props="(d) => ({ class: d.item.broken ? 'broken-row' : '' })"
      >
        <template #item.name="{ item }">
          <!-- A broken kit's detail page (read_kit_outline) would itself error,
               so render the name as plain text rather than a link. -->
          <span
            v-if="item.broken"
            class="font-weight-medium d-inline-flex align-center text-error"
          >
            <v-icon size="small" class="mr-1">mdi-alert</v-icon>
            {{ item.name }}
          </span>
          <router-link
            v-else
            class="text-primary font-weight-medium"
            :to="{ name: 'kit-detail', params: { name: item.name } }"
          >
            {{ item.name }}
          </router-link>
        </template>
        <template #item.description="{ item }">
          <span v-if="item.broken" class="text-error">
            {{ item.error || 'Kit is broken and cannot be loaded.' }}
          </span>
          <span v-else>{{ item.description }}</span>
        </template>
        <template #item.source_layer="{ item }">
          <StatusChip v-if="item.source_layer" :label="item.source_layer" />
          <span v-else class="text-medium-emphasis">—</span>
        </template>
        <template #item.versions="{ item }">
          <v-chip
            v-for="v in item.versions"
            :key="v"
            size="small"
            class="mr-1 font-mono"
            variant="tonal"
          >
            {{ v }}
          </v-chip>
        </template>
        <template #item.actions="{ item }">
          <v-btn
            v-if="isEditor"
            icon="mdi-delete-outline"
            size="small"
            variant="text"
            color="error"
            @click="deleteTarget = item.name"
          />
        </template>
        <template #expanded-row="{ item, columns }">
          <tr>
            <td :colspan="columns.length" class="py-3">
              <div
                v-if="item.matchedFields?.length"
                class="mb-2 d-flex align-center ga-1 flex-wrap"
              >
                <span class="text-caption text-medium-emphasis mr-1">
                  Matched:
                </span>
                <v-chip
                  v-for="field in item.matchedFields"
                  :key="field"
                  size="x-small"
                  variant="tonal"
                >
                  {{ field }}
                </v-chip>
              </div>
              <v-list
                v-if="item.matchedSections?.length"
                density="compact"
                class="bg-transparent"
              >
                <v-list-item
                  v-for="section in item.matchedSections"
                  :key="section.id"
                  :to="{
                    name: 'kit-edit',
                    params: {
                      name: item.name,
                      version: item.latest_version,
                    },
                    query: { section: section.id },
                  }"
                >
                  <v-list-item-title>{{ section.title }}</v-list-item-title>
                  <v-list-item-subtitle>
                    {{ section.snippet }}
                  </v-list-item-subtitle>
                </v-list-item>
              </v-list>
              <span
                v-if="!item.matchedFields?.length && !item.matchedSections?.length"
                class="text-caption text-medium-emphasis"
              >
                No content matches beyond name/summary.
              </span>
            </td>
          </tr>
        </template>
      </v-data-table>
    </v-card>

    <v-dialog v-model="createOpen" max-width="520">
      <v-card title="New kit">
        <v-card-text>
          <v-alert
            v-if="createError"
            type="error"
            variant="tonal"
            class="mb-3"
            :text="createError"
          />
          <v-text-field
            v-model="newName"
            label="Kit name"
            :rules="[nameRule]"
            placeholder="module-example"
          />
          <v-text-field v-model="newSummary" label="Summary" />
          <p class="text-caption text-medium-emphasis">
            Creates a kit with one always-load invariant section. Edit its
            sections and applicability afterwards.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="createOpen = false">Cancel</v-btn>
          <v-btn color="primary" @click="submitCreate">Create</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog :model-value="!!deleteTarget" max-width="420">
      <v-card title="Delete kit">
        <v-card-text>
          Delete <strong>{{ deleteTarget }}</strong> and all its versions? This
          cannot be undone.
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="deleteTarget = null">Cancel</v-btn>
          <v-btn color="error" @click="confirmDelete">Delete</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
:deep(.broken-row) {
  background-color: rgba(var(--v-theme-error), 0.08);
}
</style>
