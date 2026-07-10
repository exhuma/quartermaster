import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// Install a controllable matchMedia BEFORE the composable module is imported,
// so its module-scoped `prefersDark` seed and the OS-change listener bind to
// this stub. (vi.hoisted runs before the static imports below.)
const media = vi.hoisted(() => {
  const state = {
    matches: false,
    handlers: [] as ((e: { matches: boolean }) => void)[],
  }
  globalThis.matchMedia = ((query: string) => ({
    matches: state.matches,
    media: query,
    addEventListener: (_: string, h: (e: { matches: boolean }) => void) =>
      state.handlers.push(h),
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  })) as unknown as typeof globalThis.matchMedia
  return state
})

import { THEME_STORAGE_KEY, useThemeMode } from '@/composables/useThemeMode'

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
})

const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'instructionsLight',
    themes: {
      instructionsLight: { dark: false, colors: {} },
      instructionsDark: { dark: true, colors: {} },
    },
  },
})

// Mount a tiny harness so useThemeMode runs inside a Vuetify-provided context.
function mountHarness() {
  const Harness = defineComponent({
    setup: () => useThemeMode(),
    render: () => h('div'),
  })
  const wrapper = mount(Harness, { global: { plugins: [vuetify] } })
  return wrapper
}

beforeEach(() => {
  window.localStorage.clear()
})

// Simulate the OS flipping its colour scheme.
function setOsDark(matches: boolean) {
  media.matches = matches
  media.handlers.forEach((h) => h({ matches }))
}

describe('useThemeMode', () => {
  it('persists an explicit dark choice and switches Vuetify to it', async () => {
    const wrapper = mountHarness()
    wrapper.vm.setMode('dark')
    expect(wrapper.vm.mode).toBe('dark')
    expect(wrapper.vm.isDark).toBe(true)
    expect(wrapper.vm.effectiveName).toBe('instructionsDark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(vuetify.theme.global.name.value).toBe('instructionsDark')
    wrapper.unmount()
  })

  it('persists an explicit light choice regardless of the OS setting', async () => {
    setOsDark(true) // OS says dark…
    const wrapper = mountHarness()
    wrapper.vm.setMode('light') // …but the user forces light.
    expect(wrapper.vm.isDark).toBe(false)
    expect(wrapper.vm.effectiveName).toBe('instructionsLight')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
    wrapper.unmount()
  })

  it('follows the OS live when in system mode', async () => {
    const wrapper = mountHarness()
    wrapper.vm.setMode('system')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('system')

    setOsDark(true)
    expect(wrapper.vm.isDark).toBe(true)
    setOsDark(false)
    expect(wrapper.vm.isDark).toBe(false)
    wrapper.unmount()
  })
})
