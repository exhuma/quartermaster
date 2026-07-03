import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

const tokens = ref<Array<{ id: string; label: string; created: string }>>([])
const fetchTokens = vi.fn(async () => {})
const mint = vi.fn(async (_label: string) => ({
  id: '1',
  label: 'l',
  created: 'now',
  token: 'secret',
}))
const revoke = vi.fn(async (_id: string) => {})

vi.mock('@/composables/useAppTokens', () => ({
  useAppTokens: () => ({ tokens, fetchTokens, mint, revoke }),
}))

import AppTokensCard from '@/components/AppTokensCard.vue'

// Vuetify's display composable reads matchMedia / ResizeObserver, which jsdom
// does not implement. Stub them so components mount.
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

function mountCard() {
  return mount(AppTokensCard, {
    global: { plugins: [vuetify] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  tokens.value = []
})

describe('AppTokensCard', () => {
  it('fetches tokens on mount and shows the empty state', () => {
    const wrapper = mountCard()
    expect(fetchTokens).toHaveBeenCalled()
    expect(wrapper.text()).toContain('No app tokens yet.')
    wrapper.unmount()
  })

  it('lists tokens from the composable', () => {
    tokens.value = [{ id: 'abc', label: 'opencode', created: '2026-07-03' }]
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('opencode')
    expect(wrapper.text()).toContain('abc · 2026-07-03')
    wrapper.unmount()
  })

  it('documents the MCP bearer use', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('Authorization: Bearer')
    wrapper.unmount()
  })

  it('revokes a token when its delete button is clicked', async () => {
    tokens.value = [{ id: 'abc', label: 'opencode', created: '2026-07-03' }]
    const wrapper = mountCard()
    // The list item's only button is the delete action.
    await wrapper.find('.v-list-item button').trigger('click')
    expect(revoke).toHaveBeenCalledWith('abc')
    wrapper.unmount()
  })

  // The mint flow (dialog → api call → list refresh) is covered by
  // useAppTokens.test.ts; the v-dialog overlay needs browser globals jsdom
  // lacks (visualViewport), so it is not exercised here.
})
