<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useTheme } from 'vuetify'

import BaseChart from '@/components/BaseChart.vue'
import ChartCard from '@/components/ChartCard.vue'
import { useMetrics } from '@/composables/useMetrics'
import type { MetricsGranularity, MetricsWindow } from '@/types/metrics'
import {
  catalogGrowthOption,
  heatmapOption,
  kitUsageOption,
  palette,
  pieOption,
  tokensOption,
  toolLatencyOption,
} from './metricsCharts'

const {
  overview,
  error,
  window,
  granularity,
  fetchMetrics,
  setWindow,
  setGranularity,
} = useMetrics()
const theme = useTheme()
// Vuetify types colours as string | number | <colour object>, but at runtime
// these theme tokens are hex strings; coerce to the plain map the builders use.
const colors = computed(
  () => theme.current.value.colors as unknown as Record<string, string>
)
const pal = computed(() => palette(colors.value))

const windows: { value: MetricsWindow; label: string }[] = [
  { value: '24h', label: '24 hours' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
]

onMounted(fetchMetrics)

// The OTLP export state is shown as a chip purely for context — this whole
// view reads the local store, so it is populated regardless of OTEL health.
const otelChip = computed(() => {
  const status = overview.value?.meta.otel_status ?? 'unknown'
  const map: Record<string, { color: string; text: string }> = {
    exporting: { color: 'success', text: 'OTEL: exporting' },
    inert: { color: 'grey', text: 'OTEL: not configured' },
    failing: { color: 'error', text: 'OTEL: export failing' },
    configured: { color: 'warning', text: 'OTEL: configured' },
    unknown: { color: 'grey', text: 'OTEL: unknown' },
  }
  return map[status] ?? map.unknown
})

const totalDelivered = computed(() =>
  (overview.value?.tokens_timeseries ?? []).reduce(
    (sum, p) => sum + p.delivered,
    0
  )
)

// Chart options — safe to build from empty data (the builders handle it); the
// ChartCard `empty` flags below decide whether to render or show the hint.
const kitUsage = computed(() =>
  kitUsageOption(overview.value?.kit_usage ?? [], colors.value)
)
const tokens = computed(() =>
  tokensOption(overview.value?.tokens_timeseries ?? [], colors.value)
)
const structural = computed(() =>
  heatmapOption(
    overview.value?.structural_overlap ?? { kits: [], cells: [] },
    colors.value,
    'structural'
  )
)
const behavioural = computed(() =>
  heatmapOption(
    overview.value?.co_occurrence ?? { kits: [], cells: [] },
    colors.value,
    'behavioural'
  )
)
const engineMix = computed(() =>
  pieOption(overview.value?.resolve_health.engine_mix ?? {}, pal.value)
)
const confidenceMix = computed(() =>
  pieOption(overview.value?.resolve_health.confidence_mix ?? {}, pal.value)
)
const toolLatency = computed(() =>
  toolLatencyOption(overview.value?.tool_latency ?? [], colors.value)
)
const catalogGrowth = computed(() =>
  catalogGrowthOption(
    overview.value?.catalog_growth ?? { catalog: [], delivered: [] },
    pal.value
  )
)

const health = computed(() => overview.value?.resolve_health)
</script>

<template>
  <v-container fluid>
    <div class="d-flex align-center flex-wrap mb-4 ga-3">
      <h1 class="text-h5 font-weight-medium">Metrics</h1>
      <v-chip :color="otelChip.color" size="small" variant="tonal">
        {{ otelChip.text }}
      </v-chip>
      <v-spacer />
      <v-btn-toggle
        :model-value="window"
        mandatory
        density="comfortable"
        variant="outlined"
        divided
        @update:model-value="(w) => setWindow(w as MetricsWindow)"
      >
        <v-btn v-for="w in windows" :key="w.value" :value="w.value">
          {{ w.label }}
        </v-btn>
      </v-btn-toggle>
      <v-switch
        :model-value="granularity"
        true-value="1h"
        false-value="1d"
        :label="granularity === '1h' ? 'Hourly' : 'Daily'"
        color="primary"
        density="compact"
        hide-details
        class="flex-grow-0"
        @update:model-value="
          (g) => setGranularity((g ?? '1d') as MetricsGranularity)
        "
      />
      <v-btn
        icon="mdi-refresh"
        variant="text"
        aria-label="Refresh"
        @click="fetchMetrics()"
      />
    </div>

    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      class="mb-4"
      :text="error"
    />

    <p class="text-body-2 text-medium-emphasis mb-4">
      A short, always-on rolling window ({{
        overview?.meta.retention_days ?? 7
      }}
      days) kept locally so it survives restarts and works even when OTEL is
      down. For long-term history, use your OTEL/Grafana stack.
    </p>

    <v-row>
      <v-col cols="12" md="6">
        <ChartCard
          title="Kit usage"
          what-it-shows="How many times each kit's content was actually sent to a client in the window."
          how-to-read="Long bars at the top are heavily-used kits. Bars near zero (or kits missing entirely) see almost no use — candidates to retire or to make easier to discover."
          :empty="(overview?.kit_usage.length ?? 0) === 0"
        >
          <BaseChart :option="kitUsage" :height="360" />
        </ChartCard>
      </v-col>

      <v-col cols="12" md="6">
        <ChartCard
          title="Tokens sent to clients"
          :what-it-shows="`Tokens delivered over time (${totalDelivered.toLocaleString()} in this window). 'Delivered' is content actually sent; 'offered' is left for on-demand fetch and is not sent yet.`"
          how-to-read="Lower delivered tokens for the same amount of work is better — it means less of the client's context is spent. Watch the delivered line, not offered."
          :empty="(overview?.tokens_timeseries.length ?? 0) === 0"
        >
          <BaseChart :option="tokens" :height="360" />
        </ChartCard>
      </v-col>

      <v-col cols="12" md="6">
        <ChartCard
          title="Kit overlap — by declared coverage"
          what-it-shows="How similar two kits are in what they claim to cover (languages, frameworks, contexts, domains). Always available, even before any usage."
          how-to-read="A bright off-diagonal cell means two kits target very similar things — a sign of possible redundancy. Dark means they are distinct."
          :empty="(overview?.structural_overlap.kits.length ?? 0) < 2"
        >
          <BaseChart :option="structural" :height="380" />
        </ChartCard>
      </v-col>

      <v-col cols="12" md="6">
        <ChartCard
          title="Kit overlap — by real usage"
          what-it-shows="How often two kits are delivered together in the same resolve."
          how-to-read="Cross-reference with the chart on the left. Bright in BOTH → likely redundant (merge them). Bright here but dark on the left → complementary kits that form a natural bundle (a good synergy)."
          :empty="(overview?.co_occurrence.kits.length ?? 0) < 2"
        >
          <BaseChart :option="behavioural" :height="380" />
        </ChartCard>
      </v-col>

      <v-col cols="12">
        <ChartCard
          title="Selection health"
          what-it-shows="How the resolver made its choices: which inference engine won, how confident it was, how much of the task it covered, and how often it recommended broadening."
          how-to-read="Mostly 'lexical' engine or lots of 'low' confidence suggests the selector is guessing — improve traits or kit applicability. Coverage near 1.0 and a low broadening rate is healthy."
          :empty="(health?.total_calls ?? 0) === 0"
        >
          <v-row>
            <v-col cols="12" sm="6" md="3">
              <div class="text-caption text-medium-emphasis mb-1">
                Engine mix
              </div>
              <BaseChart :option="engineMix" :height="200" />
            </v-col>
            <v-col cols="12" sm="6" md="3">
              <div class="text-caption text-medium-emphasis mb-1">
                Confidence mix
              </div>
              <BaseChart :option="confidenceMix" :height="200" />
            </v-col>
            <v-col cols="12" md="6" class="d-flex flex-column justify-center">
              <div class="d-flex ga-6 flex-wrap">
                <div>
                  <div class="text-h5">{{ health?.total_calls ?? 0 }}</div>
                  <div class="text-caption text-medium-emphasis">
                    resolve calls
                  </div>
                </div>
                <div>
                  <div class="text-h5">
                    {{ Math.round((health?.coverage_p50 ?? 0) * 100) }}%
                  </div>
                  <div class="text-caption text-medium-emphasis">
                    median coverage
                  </div>
                </div>
                <div>
                  <div class="text-h5">
                    {{ Math.round((health?.broadening_rate ?? 0) * 100) }}%
                  </div>
                  <div class="text-caption text-medium-emphasis">
                    broadening rate
                  </div>
                </div>
              </div>
            </v-col>
          </v-row>
        </ChartCard>
      </v-col>

      <v-col cols="12" md="6">
        <ChartCard
          title="Tool latency & errors"
          what-it-shows="For each MCP tool, its typical (p50) and slow-case (p95) response time in milliseconds."
          how-to-read="p50 is the everyday experience; p95 is the slow tail. A large gap between them means occasional slow calls worth investigating."
          :empty="(overview?.tool_latency.length ?? 0) === 0"
        >
          <BaseChart :option="toolLatency" :height="320" />
        </ChartCard>
      </v-col>

      <v-col cols="12" md="6">
        <ChartCard
          title="Catalog growth vs delivery"
          what-it-shows="Total kit tokens in the catalog per domain (filled areas) against tokens actually delivered per domain (dashed lines), day by day."
          how-to-read="The point of on-demand loading: the catalog can keep growing (areas rise) while delivery for established domains stays flat (dashed lines don't climb with it)."
          :empty="(overview?.catalog_growth.catalog.length ?? 0) === 0"
        >
          <BaseChart :option="catalogGrowth" :height="320" />
        </ChartCard>
      </v-col>
    </v-row>
  </v-container>
</template>
