import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// Control the session per test via the mocked composable.
vi.mock('@/composables/useAuth')

import LandingView from '@/views/LandingView.vue'
import { useAuth } from '@/composables/useAuth'

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

// The onward links resolve route names; a stub router keeps `:to` happy.
const stub = { template: '<div />' }
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: stub },
    { path: '/catalog', name: 'kits', component: stub },
    { path: '/integration', name: 'integration', component: stub },
    { path: '/private-kits', name: 'private-kits', component: stub },
    { path: '/mount', name: 'mount', component: stub },
    { path: '/metrics', name: 'metrics', component: stub },
  ],
})

const login = vi.fn()

function mockAuth(isAuthenticated: boolean) {
  vi.mocked(useAuth).mockReturnValue({
    isAuthenticated: ref(isAuthenticated),
    login,
  } as unknown as ReturnType<typeof useAuth>)
}

async function mountView() {
  router.push('/')
  await router.isReady()
  return mount(LandingView, {
    global: { plugins: [vuetify, router] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  login.mockClear()
})

describe('LandingView', () => {
  it('always explains what Quartermaster is and how to connect', async () => {
    mockAuth(false)
    const wrapper = await mountView()
    const text = wrapper.text()
    expect(text).toContain('Quartermaster')
    expect(text).toContain('Connect an agent in three steps')
    expect(text).toContain('resolve_kits')
    expect(text).toContain('What you can do once connected')
    wrapper.unmount()
  })

  it('shows Sign in to /catalog for anonymous visitors', async () => {
    mockAuth(false)
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('Sign in')
    expect(wrapper.text()).not.toContain('Open catalog')

    const signIn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('Sign in'))
    expect(signIn).toBeTruthy()
    await signIn!.trigger('click')
    expect(login).toHaveBeenCalledWith('/catalog')
    wrapper.unmount()
  })

  it('shows Open catalog + onward links when authenticated', async () => {
    mockAuth(true)
    const wrapper = await mountView()
    const text = wrapper.text()
    expect(text).toContain('Open catalog')
    expect(text).toContain('Full integration guide')
    // No Sign in *button* (the "Sign in once" step copy still mentions it).
    const signInBtn = wrapper
      .findAll('button')
      .find((b) => b.text().trim() === 'Sign in')
    expect(signInBtn).toBeUndefined()
    wrapper.unmount()
  })
})
