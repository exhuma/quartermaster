<script setup lang="ts">
// The signature "equipment casing" card of the tactical design system:
// an elevated surface with a 1px blueprint border that lights up brass on
// hover, and an optional monospaced "serial number" pinned to the top-right.
// A thin wrapper over v-card so callers keep all its slots and props.
withDefaults(
  defineProps<{
    // Monospaced code shown top-right (e.g. "QM-ARC-001"); omit to hide.
    serial?: string
    // Disable the brass hover lift for static/among-many panels.
    hover?: boolean
  }>(),
  {
    serial: undefined,
    hover: true,
  }
)
</script>

<template>
  <v-card
    class="tactical-card"
    :class="{ 'tactical-card--hover': hover }"
    color="surface-container"
    variant="flat"
  >
    <span v-if="serial" class="qm-serial">{{ serial }}</span>
    <slot />
  </v-card>
</template>

<style scoped>
.tactical-card {
  position: relative;
  border: 1px solid rgb(var(--v-theme-outline-variant));
  transition:
    border-color 0.25s ease,
    background-color 0.25s ease;
}

.tactical-card--hover:hover {
  border-color: rgb(var(--v-theme-primary));
  background-color: rgb(var(--v-theme-surface-container-high)) !important;
}
</style>
