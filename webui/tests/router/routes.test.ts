import { describe, expect, it, vi } from 'vitest'

// Importing the real router runs `router.beforeEach(authGuard)`, which pulls in
// the OIDC user manager. Stub it (mirrors tests/router/guard.test.ts) so the
// route table can be inspected without a live IdP.
vi.mock('@/auth/oidc', () => ({
  userManager: {
    getUser: vi.fn(),
    signinRedirect: vi.fn().mockResolvedValue(undefined),
  },
}))

import router from '@/router'

describe('router table', () => {
  it('serves a public landing at /', () => {
    const resolved = router.resolve('/')
    expect(resolved.name).toBe('home')
    expect(resolved.meta.requiresAuth).toBeFalsy()
  })

  it('serves the kit list at /catalog, still named "kits"', () => {
    const resolved = router.resolve('/catalog')
    expect(resolved.name).toBe('kits')
    expect(resolved.meta.requiresAuth).toBe(true)
  })

  it('serves a public changelog at /changelog', () => {
    const resolved = router.resolve('/changelog')
    expect(resolved.name).toBe('changelog')
    expect(resolved.meta.requiresAuth).toBeFalsy()
  })

  it('does not expose the kit list at /kits (reserved by the MCP mount)', () => {
    // /kits* is the backend MCP mount and 404s in the SPA fallback, so the
    // catalog must never live there.
    expect(router.resolve('/catalog').path).not.toBe('/kits')
    expect(router.resolve('/kits').name).not.toBe('kits')
  })
})
