<script setup lang="ts">
// Thin vue-echarts wrapper: applies a transparent background, auto-resizes to
// its container, and gives every chart a consistent default height. Importing
// the echarts plugin here (side effect) registers the tree-shaken chart types
// wherever a chart is rendered.
import type { EChartsOption } from 'echarts'
import VChart from 'vue-echarts'

import '@/plugins/echarts'

withDefaults(
  defineProps<{ option: EChartsOption; height?: number }>(),
  { height: 320 }
)
</script>

<template>
  <v-chart
    class="base-chart"
    :option="option"
    autoresize
    :style="{ height: `${height}px` }"
  />
</template>

<style scoped>
.base-chart {
  width: 100%;
}
</style>
