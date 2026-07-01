<script setup lang="ts">
// A dashboard card that frames every chart with a plain-language explanation:
// one line on WHAT it shows and one on HOW to read it (the audience is not a
// data analyst). Renders a friendly empty-state when there is no data yet.
withDefaults(
  defineProps<{
    title: string
    whatItShows: string
    howToRead: string
    empty?: boolean
    emptyText?: string
  }>(),
  {
    empty: false,
    emptyText: 'No data yet — use some kits and refresh.',
  }
)
</script>

<template>
  <v-card class="mb-4" :title="title" variant="flat" border>
    <v-card-text>
      <p class="text-body-2 mb-1">
        <strong>What it shows:</strong> {{ whatItShows }}
      </p>
      <p class="text-body-2 text-medium-emphasis mb-4">
        <strong>How to read it:</strong> {{ howToRead }}
      </p>
      <div
        v-if="empty"
        class="d-flex align-center justify-center text-medium-emphasis chart-empty"
      >
        {{ emptyText }}
      </div>
      <slot v-else />
    </v-card-text>
  </v-card>
</template>

<style scoped>
.chart-empty {
  min-height: 160px;
  font-style: italic;
}
</style>
