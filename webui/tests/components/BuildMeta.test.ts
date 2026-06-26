import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

import BuildMeta from '@/components/BuildMeta.vue'

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

function mountBuildMeta(props: Record<string, unknown> = {}) {
  return mount(BuildMeta, {
    props,
    global: { plugins: [vuetify] },
    attachTo: document.body,
  })
}

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('BuildMeta', () => {
  it('renders nothing when no build vars are set', () => {
    vi.stubEnv('VITE_GITHUB_REPO_URL', '')
    vi.stubEnv('VITE_APP_COMMIT', '')
    vi.stubEnv('VITE_APP_BUILD_TIME', '')
    const wrapper = mountBuildMeta()
    expect(wrapper.find('.build-meta').exists()).toBe(false)
    wrapper.unmount()
  })

  it('renders a safe new-tab repo link when the URL is set', () => {
    vi.stubEnv('VITE_GITHUB_REPO_URL', 'https://github.com/acme/repo')
    vi.stubEnv('VITE_APP_COMMIT', '')
    const wrapper = mountBuildMeta()
    const link = wrapper.find('a')
    expect(link.attributes('href')).toBe('https://github.com/acme/repo')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toBe('noopener noreferrer')
    wrapper.unmount()
  })

  it('shows the 7-char commit and an identicon by default', () => {
    vi.stubEnv('VITE_GITHUB_REPO_URL', '')
    vi.stubEnv('VITE_APP_COMMIT', '0123456789abcdef')
    const wrapper = mountBuildMeta()
    expect(wrapper.text()).toContain('0123456')
    expect(wrapper.text()).not.toContain('0123456789')
    const img = wrapper.find('img.build-meta__identicon')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toContain('seed=0123456')
    wrapper.unmount()
  })

  it('suppresses the external identicon when isolated', () => {
    vi.stubEnv('VITE_APP_COMMIT', '0123456789abcdef')
    const wrapper = mountBuildMeta({ isolated: true })
    expect(wrapper.find('img.build-meta__identicon').exists()).toBe(false)
    // The commit chip is still shown.
    expect(wrapper.text()).toContain('0123456')
    wrapper.unmount()
  })
})
