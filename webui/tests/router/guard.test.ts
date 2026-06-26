import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

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
  um.signinRedirect.mockResolvedValue(undefined)
})

describe('authGuard', () => {
  it('redirects unauthenticated users to Keycloak', async () => {
    um.getUser.mockResolvedValue(null)
    const result = await authGuard(route(true, '/integration'))
    expect(result).toBe(false)
    expect(um.signinRedirect).toHaveBeenCalledWith({ state: '/integration' })
  })

  it('redirects when the session is expired', async () => {
    um.getUser.mockResolvedValue({ expired: true })
    expect(await authGuard(route(true))).toBe(false)
    expect(um.signinRedirect).toHaveBeenCalled()
  })

  it('lets authenticated users through', async () => {
    um.getUser.mockResolvedValue({ expired: false })
    expect(await authGuard(route(true))).toBe(true)
    expect(um.signinRedirect).not.toHaveBeenCalled()
  })

  it('skips the check on public routes', async () => {
    expect(await authGuard(route(false))).toBe(true)
    expect(um.getUser).not.toHaveBeenCalled()
  })
})
