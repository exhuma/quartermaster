<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useRoles } from '@/composables/useRoles'
import type { RoleRow } from '@/composables/useRoles'

const { roles, error, fetchRoles, setRole, removeRole } = useRoles()

const headers = [
  { title: 'Subject', key: 'sub' },
  { title: 'Label', key: 'label' },
  { title: 'Role', key: 'role' },
  { title: 'Source', key: 'source' },
  { title: '', key: 'actions', sortable: false, align: 'end' as const },
]

const grantOpen = ref(false)
const newSub = ref('')
const newLabel = ref('')
const actionError = ref<string | null>(null)

onMounted(fetchRoles)

async function grantEditor(): Promise<void> {
  actionError.value = null
  try {
    await setRole(newSub.value, 'editor', newLabel.value)
    grantOpen.value = false
    newSub.value = ''
    newLabel.value = ''
  } catch (err) {
    actionError.value = err instanceof Error ? err.message : String(err)
  }
}

async function demote(row: RoleRow): Promise<void> {
  actionError.value = null
  try {
    // Reverting to the default role removes the stored record.
    await removeRole(row.sub)
  } catch (err) {
    actionError.value = err instanceof Error ? err.message : String(err)
  }
}

async function promote(row: RoleRow): Promise<void> {
  actionError.value = null
  try {
    await setRole(row.sub, 'editor', row.label)
  } catch (err) {
    actionError.value = err instanceof Error ? err.message : String(err)
  }
}
</script>

<template>
  <v-container>
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-medium">Users &amp; roles</h1>
      <v-spacer />
      <v-btn
        color="primary"
        prepend-icon="mdi-account-plus"
        @click="grantOpen = true"
      >
        Grant editor
      </v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      Editors can modify the shared kit catalog and manage roles. Everyone else
      is a read-only consumer. Bootstrap editors (from
      <code>QM_INITIAL_EDITORS</code>) cannot be revoked here.
    </p>

    <v-alert
      v-if="error || actionError"
      type="error"
      variant="tonal"
      class="mb-4"
      :text="error || actionError || ''"
    />

    <v-card>
      <v-data-table :headers="headers" :items="roles" item-value="sub">
        <template #item.role="{ item }">
          <v-chip
            size="small"
            :color="item.role === 'editor' ? 'primary' : undefined"
            variant="tonal"
          >
            {{ item.role }}
          </v-chip>
        </template>
        <template #item.source="{ item }">
          <v-chip
            v-if="item.source === 'bootstrap'"
            size="small"
            variant="tonal"
            color="warning"
          >
            bootstrap
          </v-chip>
          <span v-else class="text-medium-emphasis">store</span>
        </template>
        <template #item.actions="{ item }">
          <v-btn
            v-if="item.source === 'bootstrap'"
            size="small"
            variant="text"
            disabled
          >
            locked
          </v-btn>
          <v-btn
            v-else-if="item.role === 'editor'"
            size="small"
            variant="text"
            color="error"
            @click="demote(item)"
          >
            Revoke editor
          </v-btn>
          <v-btn
            v-else
            size="small"
            variant="text"
            color="primary"
            @click="promote(item)"
          >
            Make editor
          </v-btn>
        </template>
      </v-data-table>
    </v-card>

    <v-dialog v-model="grantOpen" max-width="520">
      <v-card title="Grant editor role">
        <v-card-text>
          <v-text-field
            v-model="newSub"
            label="Subject (Keycloak sub)"
            placeholder="the user's stable subject id"
          />
          <v-text-field v-model="newLabel" label="Label (optional)" />
          <p class="text-caption text-medium-emphasis">
            Use the user's stable subject (<code>sub</code>) — you can read it
            from their profile or the /api/me endpoint.
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="grantOpen = false">Cancel</v-btn>
          <v-btn color="primary" @click="grantEditor">Grant</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
