import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// The enforcement section renders independently of the (async) integration
// info, so a null-info stub is enough to exercise it.
vi.mock('@/composables/useIntegration', () => ({
  useIntegration: () => ({
    info: ref(null),
    error: ref(null),
    fetchInfo: vi.fn(),
    registerUserAgent: vi.fn(),
  }),
}))

// AppTokensCard pulls in its own composables/API; stub it to an empty shell.
vi.mock('@/components/AppTokensCard.vue', () => ({
  default: { name: 'AppTokensCard', template: '<div />' },
}))

import IntegrationView from '@/views/IntegrationView.vue'

// Vuetify's display composable reads matchMedia / ResizeObserver, absent in jsdom.
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

function mountView() {
  return mount(IntegrationView, {
    global: { plugins: [vuetify] },
    attachTo: document.body,
  })
}

describe('IntegrationView — harness enforcement', () => {
  it('renders the enforcement section and the adoption problem', () => {
    const wrapper = mountView()
    const text = wrapper.text()
    expect(text).toContain('harness enforcement')
    expect(text).toContain('The adoption problem')
    expect(text).toContain('re-called mid-task')
    wrapper.unmount()
  })

  it('inlines the canonical Claude Code hook config and scripts', () => {
    const wrapper = mountView()
    const text = wrapper.text()
    // From settings.json (?raw) — the PostToolUse matcher.
    expect(text).toContain('mcp__quartermaster__resolve_kits')
    // From the scripts (?raw) — the non-blocking PreToolUse envelope.
    expect(text).toContain('additionalContext')
    expect(text).toContain('.claude/settings.json')
    wrapper.unmount()
  })

  it('offers a per-agent tab for every researched agent', () => {
    const wrapper = mountView()
    const text = wrapper.text()
    for (const label of ['opencode', 'Cursor', 'Cline', 'Windsurf', 'Rules-only']) {
      expect(text).toContain(label)
    }
    // opencode is the default agent tab; its snippet nudges resolve_kits.
    expect(text).toContain('resolve_kits')
    wrapper.unmount()
  })
})
