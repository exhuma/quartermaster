import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/auth/oidc', () => ({
  userManager: {
    signinRedirect: vi.fn().mockResolvedValue(undefined),
  },
}))

import { userManager } from '@/auth/oidc'
import {
  authError,
  handleUnauthorized,
  notifyAuthSuccess,
  retryAuthentication,
  _resetReauthGuard,
} from '@/auth/reauthGuard'

const um = userManager as unknown as {
  signinRedirect: ReturnType<typeof vi.fn>
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  _resetReauthGuard()
})

describe('reauthGuard', () => {
  it('redirects once on the first 401', () => {
    handleUnauthorized()
    expect(um.signinRedirect).toHaveBeenCalledOnce()
    expect(authError.value).toBeNull()
  })

  it('collapses parallel 401s in one page load into a single redirect', () => {
    handleUnauthorized()
    handleUnauthorized()
    expect(um.signinRedirect).toHaveBeenCalledOnce()
  })

  it('trips the breaker when a fresh token is still rejected', () => {
    // First load: 401 → redirect, attempt counter persisted in sessionStorage.
    handleUnauthorized()
    expect(um.signinRedirect).toHaveBeenCalledOnce()

    // Simulate the post-redirect page load (redirectInFlight resets) where the
    // new token still 401s.
    _resetReauthGuardKeepingStorage()
    handleUnauthorized()

    expect(um.signinRedirect).toHaveBeenCalledOnce() // no second redirect
    expect(authError.value).not.toBeNull()
  })

  it('resets after a successful response so a later expiry redirects again', () => {
    handleUnauthorized()
    notifyAuthSuccess()
    _resetReauthGuardKeepingStorage()

    handleUnauthorized()
    expect(um.signinRedirect).toHaveBeenCalledTimes(2)
    expect(authError.value).toBeNull()
  })

  it('clears the error and redirects on retry', () => {
    authError.value = 'boom'
    retryAuthentication()
    expect(authError.value).toBeNull()
    expect(um.signinRedirect).toHaveBeenCalledOnce()
  })
})

// Mimics a fresh page load: the in-memory redirectInFlight latch resets but the
// sessionStorage attempt counter survives the redirect round-trip.
function _resetReauthGuardKeepingStorage(): void {
  const attempts = sessionStorage.getItem('reauthAttempts')
  _resetReauthGuard()
  if (attempts !== null) {
    sessionStorage.setItem('reauthAttempts', attempts)
  }
}
