import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// Editor role is toggled per-test via this ref.
const isEditorRef = ref(true)
vi.mock('@/composables/useMe', () => ({
  useMe: () => ({ isEditor: isEditorRef, fetchMe: vi.fn() }),
}))

// A one-section kit whose owning-layer editability is set per-test.
const editableRef = ref(true)
const getOutline = vi.fn(async () => ({
  name: 'demo',
  version: 'v1',
  summary: 'Demo',
  sections: [
    { id: 'invariant', title: 'Core', gloss: 'g', always_load: true, bytes: 9 },
  ],
}))
const getSection = vi.fn(async () => ({
  id: 'invariant',
  title: 'Core',
  gloss: 'Core invariants',
  always_load: true,
  body: '# Heading\n\nSome **bold** body text.',
}))
const getDetail = vi.fn(async () => ({
  name: 'demo',
  versions: ['v1'],
  latest_version: 'v1',
  source_layer: 'base',
  editable: editableRef.value,
  applicability: {},
}))
vi.mock('@/composables/useKitEditor', () => ({
  useKitEditor: () => ({
    getOutline,
    getSection,
    getDetail,
    saveSection: vi.fn(),
    deleteSection: vi.fn(),
  }),
}))

import KitEditorView from '@/views/KitEditorView.vue'

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
})

const vuetify = createVuetify({ components, directives })
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div />' } },
    { path: '/kit/:name', name: 'kit-detail', component: { template: '<div />' } },
  ],
})

async function mountView() {
  const wrapper = mount(KitEditorView, {
    props: { name: 'demo', version: 'v1' },
    global: { plugins: [vuetify, router] },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

function buttonByText(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper
    .findAll('button')
    .find((b) => b.text().trim() === label)
}

describe('KitEditorView', () => {
  it('shows a rendered read view first, revealing the form only after Edit', async () => {
    editableRef.value = true
    isEditorRef.value = true
    const wrapper = await mountView()

    // Render-first: markdown is shown, no editable textarea yet.
    expect(wrapper.find('.markdown-body h1').text()).toBe('Heading')
    expect(wrapper.find('textarea').exists()).toBe(false)

    const edit = buttonByText(wrapper, 'Edit')
    expect(edit).toBeTruthy()
    await edit!.trigger('click')
    await flushPromises()

    // The edit form (with the markdown-body textarea) is now revealed.
    expect(wrapper.find('textarea').exists()).toBe(true)
    wrapper.unmount()
  })

  it('hides all edit affordances for a read-only kit', async () => {
    editableRef.value = false
    isEditorRef.value = true
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('read-only layer')
    expect(buttonByText(wrapper, 'Edit')).toBeUndefined()
    expect(buttonByText(wrapper, 'Add section')).toBeUndefined()
    // Still shows the rendered content.
    expect(wrapper.find('.markdown-body').exists()).toBe(true)
    wrapper.unmount()
  })
})
