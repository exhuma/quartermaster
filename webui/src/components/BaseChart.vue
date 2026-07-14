<script setup lang="ts">
// Thin vue-echarts wrapper: applies a transparent background, auto-resizes to
// its container, and gives every chart a consistent default height. Importing
// the echarts plugin here (side effect) registers the tree-shaken chart types
// wherever a chart is rendered.
//
// It also layers the active Vuetify theme's colours onto each option's chrome
// (axis labels, gridlines, legend text) via `withChartTheme`, so charts stay
// legible in both light and dark mode. Doing it here — the single seam every
// chart passes through — means individual chart builders never repeat it and
// new charts are themed automatically. Reactive to `theme.current`, so a live
// theme toggle re-themes the chart.
import type { EChartsOption } from 'echarts'
import { computed } from 'vue'
import { useTheme } from 'vuetify'
import VChart from 'vue-echarts'

import '@/plugins/echarts'
import { withChartTheme } from '@/views/metricsCharts'

const props = withDefaults(
  defineProps<{ option: EChartsOption; height?: number }>(),
  { height: 320 }
)

const theme = useTheme()
const themedOption = computed(() =>
  withChartTheme(
    props.option,
    theme.current.value.colors as unknown as Record<string, string>
  )
)
</script>

<template>
  <v-chart
    class="base-chart"
    :option="themedOption"
    autoresize
    :style="{ height: `${height}px` }"
  />
</template>

<style scoped>
.base-chart {
  width: 100%;
}
</style>
