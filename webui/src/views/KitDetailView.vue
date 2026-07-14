<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useTheme } from 'vuetify'

import { useKitEditor } from '@/composables/useKitEditor'
import { useKitMetrics } from '@/composables/useKitMetrics'
import { useMe } from '@/composables/useMe'
import BaseChart from '@/components/BaseChart.vue'
import ChartCard from '@/components/ChartCard.vue'
import FieldHelp from '@/components/FieldHelp.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import { applicabilityHelp } from '@/constants/fieldHelp'
import { versionAdoptionOption } from '@/views/metricsCharts'
import type {
  Applicability,
  KitDetail,
  TraitMap,
  VersionCompare,
} from '@/types/kit'

const props = defineProps<{ name: string }>()

const editor = useKitEditor()
const { isEditor, fetchMe } = useMe()
const { adoption, fetchAdoption } = useKitMetrics()
const theme = useTheme()
const colors = computed(
  () => theme.current.value.colors as unknown as Record<string, string>
)

const detail = ref<KitDetail | null>(null)
const manifest = reactive<Applicability>(emptyManifest())
const manifestError = ref<string | null>(null)
const manifestSaved = ref(false)

const changelog = ref('')
const compareFrom = ref('')
const compareTo = ref('')
const comparison = ref<VersionCompare | null>(null)

const traitCategories: (keyof TraitMap)[] = [
  'languages',
  'frameworks',
  'capabilities',
  'contexts',
]

const versions = computed(() => detail.value?.versions ?? [])
// The adoption chart is only meaningful once a kit has shipped a breaking
// change (more than one major); single-version kits never render it.
const isMultiVersion = computed(() => versions.value.length > 1)
const adoptionOption = computed(() =>
  versionAdoptionOption(
    adoption.value ?? {
      meta: {
        kit: props.name,
        window: '30d',
        granularity: '1d',
        generated_at: 0,
        retention_days: 0,
        store_enabled: false,
        available_versions: [],
      },
      granularity: '1d',
      versions: [],
      buckets: [],
    },
    colors.value,
    '1d'
  )
)
const adoptionEmpty = computed(
  () => (adoption.value?.buckets.length ?? 0) === 0
)

function emptyTraitMap(): TraitMap {
  return { languages: [], frameworks: [], capabilities: [], contexts: [] }
}

function emptyManifest(): Applicability {
  return {
    kit_type: 'module',
    summary: '',
    domains: [],
    languages: [],
    frameworks: [],
    contexts: [],
    requires: emptyTraitMap(),
    excludes: emptyTraitMap(),
    optional_signals: [],
    related_kits: [],
    priority: 50,
  }
}

onMounted(async () => {
  fetchMe()
  await editor.loadTraits()
  detail.value = await editor.getDetail(props.name)
  Object.assign(manifest, await editor.getApplicability(props.name))
  changelog.value = (await editor.getChangelog(props.name)).changelog
  compareFrom.value = versions.value[0] ?? ''
  compareTo.value = versions.value[versions.value.length - 1] ?? ''
  if (isMultiVersion.value) {
    await fetchAdoption(props.name)
  }
})

async function saveManifest(): Promise<void> {
  manifestError.value = null
  manifestSaved.value = false
  try {
    Object.assign(
      manifest,
      await editor.saveApplicability(props.name, { ...manifest })
    )
    manifestSaved.value = true
  } catch (err) {
    manifestError.value = err instanceof Error ? err.message : String(err)
  }
}

async function runCompare(): Promise<void> {
  comparison.value = await editor.compareVersions(
    props.name,
    compareFrom.value,
    compareTo.value
  )
}
</script>

<template>
  <v-container>
    <div class="d-flex align-center mb-4">
      <v-btn
        icon="mdi-arrow-left"
        variant="text"
        :to="{ name: 'kits' }"
        class="mr-2"
      />
      <h1 class="text-h5 font-weight-medium">{{ name }}</h1>
    </div>

    <v-row>
      <v-col cols="12" md="6">
        <v-card title="Versions" class="mb-4">
          <template v-if="detail && !detail.editable" #append>
            <v-chip
              size="small"
              variant="tonal"
              color="warning"
              prepend-icon="mdi-lock-outline"
            >
              Read-only
            </v-chip>
          </template>
          <v-card-text>
            <v-alert
              v-if="detail && !detail.editable"
              type="info"
              variant="tonal"
              density="compact"
              class="mb-3"
              text="This kit comes from a read-only layer (e.g. an external
                sync), so its sections cannot be edited here."
            />
            <div
              v-for="v in versions"
              :key="v"
              class="d-flex align-center mb-2"
            >
              <v-chip class="mr-2" variant="tonal">{{ v }}</v-chip>
              <v-spacer />
              <v-btn
                v-if="isEditor && detail?.editable"
                size="small"
                variant="text"
                color="primary"
                :to="{ name: 'kit-edit', params: { name, version: v } }"
              >
                Edit sections
              </v-btn>
              <v-btn
                v-else
                size="small"
                variant="text"
                :to="{ name: 'kit-edit', params: { name, version: v } }"
              >
                View sections
              </v-btn>
            </div>
          </v-card-text>
        </v-card>

        <v-card title="Compare versions">
          <v-card-text>
            <div class="d-flex align-center ga-2 mb-3">
              <v-select
                v-model="compareFrom"
                :items="versions"
                label="From"
                density="compact"
                hide-details
              />
              <v-select
                v-model="compareTo"
                :items="versions"
                label="To"
                density="compact"
                hide-details
              />
              <v-btn color="primary" @click="runCompare">Compare</v-btn>
            </div>
            <v-alert
              v-if="comparison?.user_facing_warning"
              type="warning"
              variant="tonal"
              class="mb-2"
              text="Contains changes that may affect end-users."
            />
            <div v-for="c in comparison?.changes ?? []" :key="c.version">
              <div class="font-weight-medium">{{ c.version }}</div>
              <MarkdownView :source="c.summary" />
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card title="Applicability">
          <v-card-text>
            <v-alert
              v-if="manifestError"
              type="error"
              variant="tonal"
              class="mb-3"
              :text="manifestError"
            />
            <v-alert
              v-else-if="manifestSaved"
              type="success"
              variant="tonal"
              class="mb-3"
              text="Saved."
            />
            <v-select
              v-model="manifest.kit_type"
              :items="editor.traits.value?.kit_types ?? []"
              label="Kit type"
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.kit_type" />
              </template>
            </v-select>
            <v-text-field
              v-model="manifest.summary"
              label="Summary"
              :counter="150"
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.summary" />
              </template>
            </v-text-field>
            <v-text-field
              v-model.number="manifest.priority"
              type="number"
              label="Priority"
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.priority" />
              </template>
            </v-text-field>
            <v-combobox
              v-model="manifest.domains"
              :items="editor.traits.value?.domains ?? []"
              label="Domains"
              multiple
              chips
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.domains" />
              </template>
            </v-combobox>
            <v-combobox
              v-model="manifest.languages"
              :items="editor.traits.value?.languages ?? []"
              label="Languages"
              multiple
              chips
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.languages" />
              </template>
            </v-combobox>
            <v-combobox
              v-model="manifest.frameworks"
              :items="editor.traits.value?.frameworks ?? []"
              label="Frameworks"
              multiple
              chips
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.frameworks" />
              </template>
            </v-combobox>
            <v-combobox
              v-model="manifest.contexts"
              :items="editor.traits.value?.contexts ?? []"
              label="Contexts"
              multiple
              chips
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.contexts" />
              </template>
            </v-combobox>

            <div class="text-subtitle-2 mt-2 d-flex align-center">
              Requires <FieldHelp :text="applicabilityHelp.requires" />
            </div>
            <v-combobox
              v-for="cat in traitCategories"
              :key="`req-${cat}`"
              v-model="manifest.requires[cat]"
              :items="editor.traits.value?.[cat] ?? []"
              :label="cat"
              multiple
              chips
              density="compact"
            />

            <div class="text-subtitle-2 mt-2 d-flex align-center">
              Excludes <FieldHelp :text="applicabilityHelp.excludes" />
            </div>
            <v-combobox
              v-for="cat in traitCategories"
              :key="`exc-${cat}`"
              v-model="manifest.excludes[cat]"
              :items="editor.traits.value?.[cat] ?? []"
              :label="cat"
              multiple
              chips
              density="compact"
            />

            <v-combobox
              v-model="manifest.optional_signals"
              :items="editor.traits.value?.optional_signals ?? []"
              label="Optional signals"
              multiple
              chips
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.optional_signals" />
              </template>
            </v-combobox>
            <v-combobox
              v-model="manifest.related_kits"
              label="Related kits"
              multiple
              chips
              density="compact"
            >
              <template #append-inner>
                <FieldHelp :text="applicabilityHelp.related_kits" />
              </template>
            </v-combobox>
          </v-card-text>
          <v-card-actions>
            <v-spacer />
            <v-btn v-if="isEditor" color="primary" @click="saveManifest">
              Save applicability
            </v-btn>
            <span v-else class="text-caption text-medium-emphasis">
              Read-only — editor role required
            </span>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <ChartCard
      v-if="isMultiVersion"
      title="Version adoption over time"
      what-it-shows="How many times each major version of this kit was served to callers, per day."
      how-to-read="Each band is a major version. A rising newer band with a shrinking older one means repos are migrating; a persistent older band means repos are still pinned to it."
      :empty="adoptionEmpty"
      empty-text="No adoption data yet — it accrues as agents resolve or fetch this kit."
    >
      <BaseChart :option="adoptionOption" :height="320" />
    </ChartCard>

    <v-card title="Changelog" class="mt-4">
      <v-card-text>
        <MarkdownView v-if="changelog" :source="changelog" />
        <span v-else class="text-medium-emphasis">No changelog.</span>
      </v-card-text>
    </v-card>
  </v-container>
</template>
