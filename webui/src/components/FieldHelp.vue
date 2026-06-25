<script setup lang="ts">
// Small inline help affordance: an information icon that reveals a description
// on hover/focus. Use it in a field's `#append-inner` slot (NOT `#label` — the
// Vuetify field label sets `pointer-events: none`, which swallows hover) or
// next to a plain heading. The text is also exposed as aria-label.
defineProps<{ text: string }>()
</script>

<template>
  <v-tooltip :text="text" location="top" max-width="320">
    <template #activator="{ props }">
      <v-icon
        v-bind="props"
        icon="mdi-information-outline"
        size="x-small"
        class="text-medium-emphasis"
        style="cursor: help"
        tabindex="0"
        role="img"
        :aria-label="text"
      />
    </template>
  </v-tooltip>
</template>
