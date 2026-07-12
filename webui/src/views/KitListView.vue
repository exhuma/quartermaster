<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useKits } from '@/composables/useKits'
import { useMe } from '@/composables/useMe'
import SectionHeader from '@/components/SectionHeader.vue'
import StatusChip from '@/components/StatusChip.vue'

const { kits, error, fetchKits, createKit, deleteKit } = useKits()
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

    <v-card>
      <v-data-table
        :headers="headers"
        :items="kits"
        item-value="name"
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
