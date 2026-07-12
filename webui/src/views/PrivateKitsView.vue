<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { usePrivateKits } from '@/composables/usePrivateKits'

const { kits, error, fetchPrivateKits, createPrivateKit, deletePrivateKit } =
  usePrivateKits()

const headers = [
  { title: 'Name', key: 'name' },
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
  'Lowercase words joined by hyphens, e.g. my-private-notes'

onMounted(fetchPrivateKits)

async function submitCreate(): Promise<void> {
  createError.value = null
  try {
    await createPrivateKit(newName.value, newSummary.value)
    createOpen.value = false
    newName.value = ''
    newSummary.value = ''
  } catch (err) {
    createError.value = err instanceof Error ? err.message : String(err)
  }
}

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value) {
    await deletePrivateKit(deleteTarget.value)
  }
  deleteTarget.value = null
}
</script>

<template>
  <v-container>
    <div class="d-flex align-center mb-2">
      <h1 class="text-h5 font-weight-medium">Private kits</h1>
      <v-chip size="small" variant="tonal" color="purple" class="ml-3">
        <v-icon start size="small">mdi-lock</v-icon>
        Visible only to you
      </v-chip>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="createOpen = true">
        New private kit
      </v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      Private kits are yours alone — no other user can see them, and they are
      resolved for you over the MCP alongside the shared catalog.
    </p>

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
          <span
            v-if="item.broken"
            class="d-inline-flex align-center text-error"
          >
            <v-icon size="small" class="mr-1">mdi-alert</v-icon>
            {{ item.name }}
          </span>
          <span v-else>{{ item.name }}</span>
        </template>
        <template #item.description="{ item }">
          <span v-if="item.broken" class="text-error">
            {{ item.error || 'Kit is broken and cannot be loaded.' }}
          </span>
          <span v-else>{{ item.description }}</span>
        </template>
        <template #item.versions="{ item }">
          <v-chip
            v-for="v in item.versions"
            :key="v"
            size="small"
            class="mr-1"
            variant="tonal"
          >
            {{ v }}
          </v-chip>
        </template>
        <template #item.actions="{ item }">
          <v-btn
            icon="mdi-delete-outline"
            size="small"
            variant="text"
            color="error"
            @click="deleteTarget = item.name"
          />
        </template>
        <template #no-data>
          <div class="pa-4 text-medium-emphasis">
            You have no private kits yet.
          </div>
        </template>
      </v-data-table>
    </v-card>

    <v-dialog v-model="createOpen" max-width="520">
      <v-card title="New private kit">
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
            placeholder="my-private-notes"
          />
          <v-text-field v-model="newSummary" label="Summary" />
          <p class="text-caption text-medium-emphasis">
            Creates a private kit with one always-load invariant section, owned
            by you.
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
      <v-card title="Delete private kit">
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
