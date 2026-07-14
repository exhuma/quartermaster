import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// Auth-less mode: the config module reports authDisabled=true. Preserve the
// module's other exports so unrelated importers keep working.
vi.mock('@/config', async () => {
  const actual = await vi.importActual<typeof import('@/config')>('@/config')
  return { ...actual, authDisabled: true }
})

vi.mock('@/composables/useAuth')
vi.mock('@/composables/useMe')
vi.mock('@/composables/useLoading')
vi.mock('@/auth/reauthGuard', () => ({
  authError: ref(null),
  retryAuthentication: vi.fn(),
}))
vi.mock('@/components/BuildMeta.vue', () => ({
  default: { name: 'BuildMeta', template: '<div />' },
}))

import App from '@/App.vue'
import { useAuth } from '@/composables/useAuth'
import { useMe } from '@/composables/useMe'
import { useLoading } from '@/composables/useLoading'

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
    { path: '/admin/users', name: 'admin-users', component: stub },
    { path: '/changelog', name: 'changelog', component: stub },
  ],
})

beforeEach(() => {
  // In auth-less mode useAuth reports an always-authenticated synthetic caller.
  vi.mocked(useAuth).mockReturnValue({
    isAuthenticated: ref(true),
    displayName: ref('local'),
    refresh: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
  vi.mocked(useMe).mockReturnValue({
    isEditor: ref(true),
    fetchMe: vi.fn(),
  } as unknown as ReturnType<typeof useMe>)
  vi.mocked(useLoading).mockReturnValue({
    isLoading: ref(false),
  } as unknown as ReturnType<typeof useLoading>)
})

async function mountApp() {
  router.push('/')
  await router.isReady()
  return mount(App, {
    global: { plugins: [vuetify, router] },
    attachTo: document.body,
  })
}

describe('App shell in auth-less mode', () => {
  it('renders the full nav but no Sign in / Sign out chrome', async () => {
    const wrapper = await mountApp()
    // Full nav (incl. Users, since the synthetic caller is an editor).
    expect(wrapper.find('.app-nav').exists()).toBe(true)
    expect(wrapper.find('.app-nav').text()).toContain('Users')
    // The synthetic label shows, but neither auth button is offered.
    expect(wrapper.text()).toContain('local')
    expect(wrapper.text()).not.toContain('Sign in')
    expect(wrapper.text()).not.toContain('Sign out')
    wrapper.unmount()
  })
})
