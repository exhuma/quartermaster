<script setup lang="ts">
// Colour-scheme switcher for the app bar. The activator icon reflects the
// currently-shown scheme (sun/moon); the menu lets the user pick System
// (follow the OS, the default), Light, or Dark. The choice is persisted and
// applied by useThemeMode.
import { computed } from 'vue'

import { useThemeMode, type ThemeMode } from '@/composables/useThemeMode'

const { mode, isDark, setMode } = useThemeMode()

const activatorIcon = computed(() =>
  isDark.value ? 'mdi-weather-night' : 'mdi-weather-sunny'
)

const options: { value: ThemeMode; title: string; icon: string }[] = [
  { value: 'system', title: 'System', icon: 'mdi-monitor' },
  { value: 'light', title: 'Light', icon: 'mdi-weather-sunny' },
  { value: 'dark', title: 'Dark', icon: 'mdi-weather-night' },
]
</script>

<template>
  <v-menu location="bottom end">
    <template #activator="{ props }">
      <v-btn
        v-bind="props"
        :icon="activatorIcon"
        variant="text"
        aria-label="Colour theme"
      />
    </template>
    <v-list density="compact" min-width="160" :selected="[mode]">
      <v-list-item
        v-for="opt in options"
        :key="opt.value"
        :value="opt.value"
        :prepend-icon="opt.icon"
        :title="opt.title"
        @click="setMode(opt.value)"
      >
        <template #append>
          <v-icon v-if="mode === opt.value" icon="mdi-check" size="small" />
        </template>
      </v-list-item>
    </v-list>
  </v-menu>
</template>
