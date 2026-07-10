<script setup lang="ts">
// A monospaced "stamped equipment" status pill. The label is shown in a
// state colour over a low-opacity tint of that same colour, so it stays
// legible on the navy surfaces without shouting. Purely presentational.
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    // Semantic state → theme colour. Free-form colours fall through to the
    // Vuetify token of the same name, defaulting to a neutral outline tone.
    status?: 'active' | 'online' | 'archived' | 'error' | 'warning' | string
  }>(),
  {
    status: 'neutral',
  }
)

// Map a semantic status onto a Vuetify theme colour token.
const color = computed(() => {
  switch (props.status) {
    case 'active':
    case 'online':
      return 'success'
    case 'archived':
    case 'neutral':
      return 'on-surface-variant'
    case 'error':
      return 'error'
    case 'warning':
      return 'warning'
    default:
      // Any other value is treated as a bare theme-colour token (e.g. "primary").
      return props.status || 'on-surface-variant'
  }
})
</script>

<template>
  <span
    class="status-chip qm-label"
    :style="{ '--chip-color': `var(--v-theme-${color})` }"
  >
    <span class="status-chip__dot" />
    {{ label }}
  </span>
</template>

<style scoped>
.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.4em;
  padding: 0.15em 0.6em;
  font-size: 0.68rem;
  line-height: 1.4;
  border-radius: 9999px;
  color: rgb(var(--chip-color));
  background-color: rgba(var(--chip-color), 0.14);
  border: 1px solid rgba(var(--chip-color), 0.3);
  white-space: nowrap;
}

.status-chip__dot {
  width: 0.42em;
  height: 0.42em;
  border-radius: 9999px;
  background-color: rgb(var(--chip-color));
}
</style>
