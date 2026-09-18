<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { usePrivatePrompts } from '@/composables/usePrivatePrompts'

const {
  prompts,
  error,
  fetchPrivatePrompts,
  fetchPrivatePrompt,
  createPrivatePrompt,
  updatePrivatePrompt,
  deletePrivatePrompt,
} = usePrivatePrompts()

const headers = [
  { title: 'Name', key: 'name' },
  { title: 'Title', key: 'title' },
  { title: 'Description', key: 'description' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const nameRule = (v: string) =>
  /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(v) ||
  'Lowercase words joined by hyphens, e.g. my-private-notes'

onMounted(fetchPrivatePrompts)

// --- Create ---------------------------------------------------------------

const createOpen = ref(false)
const newName = ref('')
const newTitle = ref('')
const newDescription = ref('')
const newBody = ref('')
const createError = ref<string | null>(null)

async function submitCreate(): Promise<void> {
  createError.value = null
  try {
    await createPrivatePrompt(
      newName.value,
      newTitle.value,
      newDescription.value,
      newBody.value
    )
    createOpen.value = false
    newName.value = ''
    newTitle.value = ''
    newDescription.value = ''
    newBody.value = ''
  } catch (err) {
    createError.value = err instanceof Error ? err.message : String(err)
  }
}

// --- Edit -------------------------------------------------------------

const editOpen = ref(false)
const editName = ref('')
const editTitle = ref('')
const editDescription = ref('')
const editBody = ref('')
const editError = ref<string | null>(null)

async function openEdit(name: string): Promise<void> {
  editError.value = null
  try {
    const detail = await fetchPrivatePrompt(name)
    editName.value = detail.name
    editTitle.value = detail.title
    editDescription.value = detail.description
    editBody.value = detail.body
    editOpen.value = true
  } catch (err) {
    editError.value = err instanceof Error ? err.message : String(err)
  }
}

async function submitEdit(): Promise<void> {
  editError.value = null
  try {
    await updatePrivatePrompt(
      editName.value,
      editTitle.value,
      editDescription.value,
      editBody.value
    )
    editOpen.value = false
  } catch (err) {
    editError.value = err instanceof Error ? err.message : String(err)
  }
}

// --- Delete -----------------------------------------------------------

const deleteTarget = ref<string | null>(null)

async function confirmDelete(): Promise<void> {
  if (deleteTarget.value) {
    await deletePrivatePrompt(deleteTarget.value)
  }
  deleteTarget.value = null
}
</script>

<template>
  <v-container>
    <div class="d-flex align-center mb-2">
      <h1 class="text-h5 font-weight-medium">Private prompts</h1>
      <v-chip size="small" variant="tonal" color="purple" class="ml-3">
        <v-icon start size="small">mdi-lock</v-icon>
        Visible only to you
      </v-chip>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="createOpen = true">
        New private prompt
      </v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      Private prompts are yours alone — no other user can see them, and they are
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
        :items="prompts"
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
          <a
            v-else
            href="#"
            class="text-primary font-weight-medium"
            @click.prevent="openEdit(item.name)"
          >
            {{ item.name }}
          </a>
        </template>
        <template #item.description="{ item }">
          <span v-if="item.broken" class="text-error">
            {{ item.error || 'Prompt is broken and cannot be loaded.' }}
          </span>
          <span v-else>{{ item.description }}</span>
        </template>
        <template #item.actions="{ item }">
          <v-btn
            icon="mdi-pencil-outline"
            size="small"
            variant="text"
            @click="openEdit(item.name)"
          />
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
            You have no private prompts yet.
          </div>
        </template>
      </v-data-table>
    </v-card>

    <v-dialog v-model="createOpen" max-width="640">
      <v-card title="New private prompt">
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
            label="Prompt name"
            :rules="[nameRule]"
            placeholder="my-private-notes"
          />
          <v-text-field v-model="newTitle" label="Title" />
          <v-text-field v-model="newDescription" label="Description" />
          <v-textarea
            v-model="newBody"
            label="Body"
            rows="10"
            auto-grow
            placeholder="Prompt Markdown content"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="createOpen = false">Cancel</v-btn>
          <v-btn color="primary" @click="submitCreate">Create</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="editOpen" max-width="640">
      <v-card :title="`Edit ${editName}`">
        <v-card-text>
          <v-alert
            v-if="editError"
            type="error"
            variant="tonal"
            class="mb-3"
            :text="editError"
          />
          <v-text-field v-model="editTitle" label="Title" />
          <v-text-field v-model="editDescription" label="Description" />
          <v-textarea v-model="editBody" label="Body" rows="10" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="editOpen = false">Cancel</v-btn>
          <v-btn color="primary" @click="submitEdit">Save</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog :model-value="!!deleteTarget" max-width="420">
      <v-card title="Delete private prompt">
        <v-card-text>
          Delete <strong>{{ deleteTarget }}</strong
          >? This cannot be undone.
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
