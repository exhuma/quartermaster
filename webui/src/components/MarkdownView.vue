<script setup lang="ts">
// Renders a markdown string as formatted HTML (headings, lists, fenced code,
// links). Used for kit changelogs and kit section bodies, which are authored
// as full block markdown and were previously shown as raw <pre> text.
//
// Safety: markdown-it runs with `html: false`, so raw HTML in the source is
// escaped rather than emitted, and its default `validateLink` blocks
// dangerous URL schemes (javascript:, data:, vbscript:). That makes the
// rendered output safe to inject via v-html without a separate sanitizer.
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'

const props = defineProps<{ source: string | null | undefined }>()

// A single shared parser instance; markdown-it is stateless across render().
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
})

// Open links in a new tab safely (rel guards against reverse-tabnabbing).
const defaultLinkOpen =
  md.renderer.rules.link_open ??
  ((tokens, idx, options, _env, self) =>
    self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

const html = computed(() => md.render(props.source ?? ''))
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- output is markdown-it with
       html:false + link validation; see the component comment. -->
  <div class="markdown-body" v-html="html" />
</template>

<style scoped>
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  font-weight: 600;
  line-height: 1.3;
  margin: 1rem 0 0.5rem;
}

.markdown-body :deep(h1) {
  font-size: 1.4rem;
}

.markdown-body :deep(h2) {
  font-size: 1.2rem;
}

.markdown-body :deep(h3) {
  font-size: 1.05rem;
}

.markdown-body :deep(p),
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.5rem 0;
}

.markdown-body :deep(:first-child) {
  margin-top: 0;
}

.markdown-body :deep(:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(code) {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.85em;
  background: rgba(var(--v-theme-on-surface), 0.08);
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
}

.markdown-body :deep(pre) {
  background: rgba(var(--v-theme-on-surface), 0.06);
  padding: 0.75rem 1rem;
  border-radius: 6px;
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
}

.markdown-body :deep(a) {
  color: rgb(var(--v-theme-primary));
}

.markdown-body :deep(blockquote) {
  border-left: 2px solid rgba(var(--v-theme-on-surface), 0.2);
  padding-left: 1rem;
  margin: 0.5rem 0;
  color: rgba(var(--v-theme-on-surface), 0.8);
}
</style>
