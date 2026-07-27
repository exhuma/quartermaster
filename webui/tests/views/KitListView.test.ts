import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

const kitsRef = ref([
  {
    name: 'kit-alpha',
    description: 'Alpha summary',
    versions: ['v1'],
    latest_version: 'v1',
    source_layer: 'base',
    editable: true,
  },
])
const fetchKits = vi.fn()
vi.mock('@/composables/useKits', () => ({
  useKits: () => ({
    kits: kitsRef,
    error: ref(null),
    fetchKits,
    createKit: vi.fn(),
    deleteKit: vi.fn(),
  }),
}))

const searchResultsRef = ref<
  {
    name: string
    version: string
    score: number
    summary: string
    matched_fields: string[]
    sections: { id: string; title: string; snippet: string; score: number }[]
  }[]
>([])
const searchFn = vi.fn(async () => {
  searchResultsRef.value = [
    {
      name: 'kit-alpha',
      version: 'v1',
      score: 30,
      summary: 'Alpha summary',
      matched_fields: ['domains:backend'],
      sections: [
        {
          id: 'tooling',
          title: 'Tooling',
          snippet: 'Use uv to sync deps',
          score: 5,
        },
      ],
    },
  ]
})
const clearFn = vi.fn(() => {
  searchResultsRef.value = []
})
vi.mock('@/composables/useKitSearch', () => ({
  useKitSearch: () => ({
    results: searchResultsRef,
    error: ref(null),
    search: searchFn,
    clear: clearFn,
  }),
}))

vi.mock('@/composables/useMe', () => ({
  useMe: () => ({ isEditor: ref(true), fetchMe: vi.fn() }),
}))

import KitListView from '@/views/KitListView.vue'

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
    { path: '/catalog', name: 'kits', component: { template: '<div />' } },
    {
      path: '/kit/:name',
      name: 'kit-detail',
      component: { template: '<div />' },
    },
    {
      path: '/kit/:name/:version',
      name: 'kit-edit',
      component: { template: '<div />' },
    },
  ],
})

function mountView() {
  return mount(KitListView, {
    global: { plugins: [vuetify, router] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  searchResultsRef.value = []
})

describe('KitListView', () => {
  it('shows the full kit list when the search box is empty', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('kit-alpha')
    expect(searchFn).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('debounces and searches once the query reaches 2 characters', async () => {
    vi.useFakeTimers()
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('input').setValue('fastapi')
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(searchFn).toHaveBeenCalledWith('fastapi')
    vi.useRealTimers()
    wrapper.unmount()
  })

  it('does not search for a single-character query', async () => {
    vi.useFakeTimers()
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('input').setValue('f')
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(searchFn).not.toHaveBeenCalled()
    vi.useRealTimers()
    wrapper.unmount()
  })

  it('falls back to the full list when the query is cleared', async () => {
    vi.useFakeTimers()
    const wrapper = mountView()
    await flushPromises()
    const input = wrapper.find('input')
    await input.setValue('fa')
    vi.advanceTimersByTime(300)
    await flushPromises()
    await input.setValue('')
    await flushPromises()
    expect(clearFn).toHaveBeenCalled()
    vi.useRealTimers()
    wrapper.unmount()
  })
})
