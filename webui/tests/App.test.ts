import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

vi.mock('@/composables/useAuth')
vi.mock('@/composables/useMe')
vi.mock('@/composables/useLoading')
// The reauth dialog reads a module-level ref; a null error keeps it closed.
vi.mock('@/auth/reauthGuard', () => ({
  authError: ref(null),
  retryAuthentication: vi.fn(),
}))
// BuildMeta pulls in build-time env; stub it to an empty shell.
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

function mockAuth(isAuthenticated: boolean) {
  vi.mocked(useAuth).mockReturnValue({
    isAuthenticated: ref(isAuthenticated),
    displayName: ref('Ada Lovelace'),
    refresh: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
}

function mockMe(isEditor: boolean) {
  vi.mocked(useMe).mockReturnValue({
    isEditor: ref(isEditor),
    fetchMe: vi.fn(),
  } as unknown as ReturnType<typeof useMe>)
}

beforeEach(() => {
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

describe('App shell', () => {
  it('shows the Quartermaster brand linking home', async () => {
    mockAuth(false)
    mockMe(false)
    const wrapper = await mountApp()
    const brand = wrapper.find('a.brand')
    expect(brand.exists()).toBe(true)
    expect(brand.text()).toContain('Quartermaster')
    expect(brand.attributes('href')).toBe('/')
    wrapper.unmount()
  })

  it('hides the in-app nav and offers Sign in when anonymous', async () => {
    mockAuth(false)
    mockMe(false)
    const wrapper = await mountApp()
    expect(wrapper.find('.app-nav').exists()).toBe(false)
    expect(wrapper.text()).toContain('Sign in')
    wrapper.unmount()
  })

  it('shows the full nav (incl. Users for editors) when authenticated', async () => {
    mockAuth(true)
    mockMe(true)
    const wrapper = await mountApp()
    expect(wrapper.find('.app-nav').exists()).toBe(true)
    const nav = wrapper.find('.app-nav').text()
    for (const label of [
      'Kits',
      'Private',
      'Integrate',
      'Mount',
      'Metrics',
      'Users',
    ]) {
      expect(nav).toContain(label)
    }
    wrapper.unmount()
  })

  it('omits the Users nav item for non-editors', async () => {
    mockAuth(true)
    mockMe(false)
    const wrapper = await mountApp()
    expect(wrapper.find('.app-nav').text()).not.toContain('Users')
    wrapper.unmount()
  })
})
