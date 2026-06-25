<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { useKitEditor } from '@/composables/useKitEditor'
import FieldHelp from '@/components/FieldHelp.vue'
import { sectionHelp } from '@/constants/fieldHelp'
import type { SectionMeta } from '@/types/kit'

const props = defineProps<{ name: string; version: string }>()

const editor = useKitEditor()

const sections = ref<SectionMeta[]>([])
const selectedId = ref<string | null>(null)
const isNew = ref(false)
const error = ref<string | null>(null)
const saved = ref(false)

const form = reactive({
  id: '',
  title: '',
  gloss: '',
  always_load: false,
  body: '',
})

const idRule = (v: string) =>
  /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(v) ||
  'Lowercase words joined by hyphens, e.g. invariant'

async function refreshOutline(): Promise<void> {
  const outline = await editor.getOutline(props.name, props.version)
  sections.value = outline.sections
}

async function select(id: string): Promise<void> {
  error.value = null
  saved.value = false
  isNew.value = false
  selectedId.value = id
  const section = await editor.getSection(props.name, props.version, id)
  Object.assign(form, section)
}

function startNew(): void {
  error.value = null
  saved.value = false
  isNew.value = true
  selectedId.value = null
  Object.assign(form, {
    id: '',
    title: '',
    gloss: '',
    always_load: false,
    body: '',
  })
}

async function save(): Promise<void> {
  error.value = null
  saved.value = false
  try {
    await editor.saveSection(props.name, props.version, form.id, {
      title: form.title,
      gloss: form.gloss,
      always_load: form.always_load,
      body: form.body,
    })
    saved.value = true
    isNew.value = false
    selectedId.value = form.id
    await refreshOutline()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
}

async function remove(): Promise<void> {
  if (!selectedId.value) {
    return
  }
  error.value = null
  try {
    await editor.deleteSection(props.name, props.version, selectedId.value)
    selectedId.value = null
    Object.assign(form, { id: '', title: '', gloss: '', body: '' })
    await refreshOutline()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
}

onMounted(async () => {
  await refreshOutline()
  if (sections.value.length > 0) {
    await select(sections.value[0].id)
  }
})
</script>

<template>
  <v-container>
    <div class="d-flex align-center mb-4">
      <v-btn
        icon="mdi-arrow-left"
        variant="text"
        :to="{ name: 'kit-detail', params: { name } }"
        class="mr-2"
      />
      <h1 class="text-h6 font-weight-medium">
        {{ name }} <span class="text-medium-emphasis">/ {{ version }}</span>
      </h1>
    </div>

    <v-row>
      <v-col cols="12" md="4">
        <v-card title="Sections">
          <v-list>
            <v-list-item
              v-for="s in sections"
              :key="s.id"
              :active="s.id === selectedId"
              :title="s.title"
              :subtitle="s.id"
              @click="select(s.id)"
            >
              <template #append>
                <v-chip
                  v-if="s.always_load"
                  size="x-small"
                  color="primary"
                  variant="tonal"
                >
                  always
                </v-chip>
              </template>
            </v-list-item>
          </v-list>
          <v-card-actions>
            <v-btn
              variant="text"
              color="primary"
              prepend-icon="mdi-plus"
              @click="startNew"
            >
              Add section
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <v-col cols="12" md="8">
        <v-card :title="isNew ? 'New section' : 'Edit section'">
          <v-card-text>
            <v-alert
              v-if="error"
              type="error"
              variant="tonal"
              class="mb-3"
              :text="error"
            />
            <v-alert
              v-else-if="saved"
              type="success"
              variant="tonal"
              class="mb-3"
              text="Saved."
            />
            <v-text-field
              v-model="form.id"
              label="Section id"
              :disabled="!isNew"
              :rules="isNew ? [idRule] : []"
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="sectionHelp.id" />
              </template>
            </v-text-field>
            <v-text-field v-model="form.title" label="Title" density="compact">
              <template #append-inner>
                <FieldHelp :text="sectionHelp.title" />
              </template>
            </v-text-field>
            <v-text-field
              v-model="form.gloss"
              label="Gloss"
              :counter="100"
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="sectionHelp.gloss" />
              </template>
            </v-text-field>
            <div class="d-flex align-center">
              <v-switch
                v-model="form.always_load"
                label="Always load"
                color="primary"
                density="compact"
                hide-details
              />
              <FieldHelp :text="sectionHelp.always_load" class="ms-1" />
            </div>
            <v-textarea
              v-model="form.body"
              label="Markdown body"
              auto-grow
              rows="12"
              class="mt-2"
            >
              <template #append-inner>
                <FieldHelp :text="sectionHelp.body" />
              </template>
            </v-textarea>
          </v-card-text>
          <v-card-actions>
            <v-btn
              v-if="!isNew && selectedId"
              color="error"
              variant="text"
              @click="remove"
            >
              Delete
            </v-btn>
            <v-spacer />
            <v-btn color="primary" :disabled="!form.id" @click="save">
              Save section
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>
