import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

// Auth-less mode: the config module reports authDisabled=true. The guard must
// then let every protected route through without ever touching the OIDC client.
vi.mock('@/config', () => ({
  authDisabled: true,
  devAuth: false,
}))

vi.mock('@/auth/oidc', () => ({
  userManager: {
    getUser: vi.fn(),
    signinRedirect: vi.fn().mockResolvedValue(undefined),
  },
}))

import { authGuard } from '@/router'
import { userManager } from '@/auth/oidc'

const um = userManager as unknown as {
  getUser: ReturnType<typeof vi.fn>
  signinRedirect: ReturnType<typeof vi.fn>
}

function route(requiresAuth: boolean, fullPath = '/'): RouteLocationNormalized {
  return {
    fullPath,
    meta: { requiresAuth },
  } as unknown as RouteLocationNormalized
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('authGuard with auth disabled', () => {
  it('lets protected routes through without an OIDC session', async () => {
    expect(await authGuard(route(true, '/integration'))).toBe(true)
    expect(um.getUser).not.toHaveBeenCalled()
    expect(um.signinRedirect).not.toHaveBeenCalled()
  })
})
