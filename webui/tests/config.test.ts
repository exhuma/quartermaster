import { afterEach, describe, expect, it, vi } from 'vitest'

// config.ts reads the global / import.meta.env at module load, so each test
// resets modules and re-imports after staging the environment.
afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('runtime config', () => {
  it('runtime global wins over the VITE fallback', async () => {
    vi.stubEnv('VITE_OIDC_AUTHORITY', 'https://env-authority')
    vi.stubGlobal('__APP_CONFIG__', {
      oidcAuthority: 'https://runtime-authority',
      oidcClientId: 'runtime-client',
    })
    const cfg = await import('@/config')
    expect(cfg.oidcAuthority).toBe('https://runtime-authority')
    expect(cfg.requiredConfigErrors()).toEqual([])
  })

  it('falls back to VITE_* when the global is absent', async () => {
    vi.stubEnv('VITE_OIDC_AUTHORITY', 'https://env-authority')
    vi.stubEnv('VITE_OIDC_CLIENT_ID', 'env-client')
    const cfg = await import('@/config')
    expect(cfg.oidcAuthority).toBe('https://env-authority')
    expect(cfg.oidcClientId).toBe('env-client')
  })

  it('devAuth is off without the explicit opt-in', async () => {
    const cfg = await import('@/config')
    expect(cfg.devAuth).toBe(false)
  })

  it('devAuth turns on with VITE_DEV_AUTH under the dev flag', async () => {
    vi.stubEnv('VITE_DEV_AUTH', 'true')
    const cfg = await import('@/config')
    expect(cfg.devAuth).toBe(true)
  })

  it('reports missing required config and asserts loudly', async () => {
    // Explicitly clear these so the test is deterministic regardless of any
    // local webui/.env a developer may have.
    vi.stubEnv('VITE_OIDC_AUTHORITY', '')
    vi.stubEnv('VITE_OIDC_CLIENT_ID', '')
    const cfg = await import('@/config')
    expect(cfg.requiredConfigErrors()).toContain('oidcAuthority')
    expect(cfg.requiredConfigErrors()).toContain('oidcClientId')
    expect(() => cfg.assertRequiredConfig()).toThrow(
      /Missing required runtime config/
    )
  })
})
