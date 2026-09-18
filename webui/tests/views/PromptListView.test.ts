import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

const promptsRef = ref([
  {
    name: 'prompt-alpha',
    title: 'Alpha',
    description: 'Alpha summary',
    source_layer: 'base',
    editable: true,
  },
])
const fetchPrompts = vi.fn()
const fetchPrompt = vi.fn(async (name: string) => ({
  name,
  title: 'Alpha',
  description: 'Alpha summary',
  source_layer: 'base',
  editable: true,
  body: 'Alpha body',
}))
const createPrompt = vi.fn()
const updatePrompt = vi.fn()
const deletePrompt = vi.fn()
vi.mock('@/composables/usePrompts', () => ({
  usePrompts: () => ({
    prompts: promptsRef,
    error: ref(null),
    fetchPrompts,
    fetchPrompt,
    createPrompt,
    updatePrompt,
    deletePrompt,
  }),
}))

const isEditorRef = ref(true)
vi.mock('@/composables/useMe', () => ({
  useMe: () => ({ isEditor: isEditorRef, fetchMe: vi.fn() }),
}))

import PromptListView from '@/views/PromptListView.vue'

beforeAll(() => {
  globalThis.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  })) as unknown as typeof globalThis.matchMedia
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  // Vuetify's overlay location strategy references the bare `visualViewport`
  // global (not `window.visualViewport`), which jsdom never defines — an
  // unstubbed reference throws ReferenceError as soon as a v-dialog opens.
  globalThis.visualViewport ??= {
    addEventListener: () => {},
    removeEventListener: () => {},
  } as unknown as VisualViewport
})

const vuetify = createVuetify({ components, directives })
const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', name: 'home', component: { template: '<div />' } }],
})

function mountView() {
  return mount(PromptListView, {
    global: { plugins: [vuetify, router] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  isEditorRef.value = true
})

describe('PromptListView', () => {
  it('shows the prompt list', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('prompt-alpha')
    expect(fetchPrompts).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('hides create/edit/delete controls for a non-editor', async () => {
    isEditorRef.value = false
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).not.toContain('New prompt')
    expect(wrapper.text()).toContain('Read-only')
    expect(wrapper.find('button[color="error"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('fetches the full prompt detail when its name is clicked', async () => {
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('a').trigger('click')
    await flushPromises()
    expect(fetchPrompt).toHaveBeenCalledWith('prompt-alpha')
    wrapper.unmount()
  })

  // The edit/create/delete v-dialog overlays need browser globals jsdom
  // lacks (visualViewport), so their open state is not exercised here — see
  // AppTokensCard.test.ts for the same constraint.
})
