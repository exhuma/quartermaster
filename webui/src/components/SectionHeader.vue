<script setup lang="ts">
// A section heading in the tactical style: a brass accent bar to the left of
// the title, an optional muted subtitle beneath, and an optional monospaced
// "[ SECTION_ROOT ]" eyebrow tag pushed to the right — the recurring header
// treatment from the mockups.
defineProps<{
  title: string
  subtitle?: string
  // Right-aligned mono tag; rendered wrapped in brackets, e.g. "SECURITY_ROOT".
  tag?: string
}>()
</script>

<template>
  <div class="section-header mb-4">
    <div class="d-flex align-center justify-space-between ga-4">
      <h2 class="section-header__title text-h5 font-weight-bold">
        {{ title }}
      </h2>
      <span v-if="tag" class="qm-section-label d-none d-sm-inline">
        [ {{ tag }} ]
      </span>
    </div>
    <p v-if="subtitle" class="text-body-2 text-on-surface-variant mb-0 mt-1">
      {{ subtitle }}
    </p>
  </div>
</template>

<style scoped>
.section-header__title {
  position: relative;
  padding-left: 0.85rem;
}

.section-header__title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.15em;
  bottom: 0.15em;
  width: 3px;
  border-radius: 2px;
  background-color: rgb(var(--v-theme-primary));
}
</style>
