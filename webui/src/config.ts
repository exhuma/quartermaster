// The ONLY place window.__APP_CONFIG__ or import.meta.env is read
// (module-runtime-config-spa). Components import named, typed values here.
//
// In production the server serves /config.js (rendered from its env) which
// sets window.__APP_CONFIG__ before the bundle loads, so one static build
// targets any environment. In local dev that global is empty and the
// build-time VITE_* values are used. The runtime value always wins.
//
// Validation is deferred to assertRequiredConfig(), called once at boot in
// main.ts (fail loudly), rather than thrown at import — so this module is
// importable in tests that assert runtime-vs-fallback precedence.

interface RuntimeConfig {
  oidcAuthority?: string
  oidcClientId?: string
  oidcRedirectUri?: string
  oidcPostLogoutUri?: string
  oidcScope?: string
  apiBaseUrl?: string
}

declare global {
  interface Window {
    __APP_CONFIG__?: RuntimeConfig
  }
}

// Dev-only auth bypass gate (module-dev-auth-bypass). The first operand is
// the bundler's statically-replaced dev flag — `import.meta.env.DEV` is
// `true` ONLY under the Vite dev server and folds to literal `false` in any
// production build, so this whole expression becomes `false` and the
// dev-login helpers are dead-code-eliminated from production artefacts. The
// second operand is an explicit opt-in, so dev login is off by default even
// locally. This is DELIBERATELY read from import.meta.env, never from the
// runtime-config global, so the production runtime-config mechanism can
// never turn it on.
export const devAuth: boolean =
  import.meta.env.DEV && import.meta.env.VITE_DEV_AUTH === 'true'

const runtime: RuntimeConfig = window.__APP_CONFIG__ ?? {}

export const oidcAuthority =
  runtime.oidcAuthority || (import.meta.env.VITE_OIDC_AUTHORITY as string)
export const oidcClientId =
  runtime.oidcClientId || (import.meta.env.VITE_OIDC_CLIENT_ID as string)
export const oidcRedirectUri =
  runtime.oidcRedirectUri ||
  (import.meta.env.VITE_OIDC_REDIRECT_URI as string) ||
  `${window.location.origin}/auth/callback`
export const oidcPostLogoutUri =
  runtime.oidcPostLogoutUri ||
  (import.meta.env.VITE_OIDC_POST_LOGOUT_URI as string) ||
  `${window.location.origin}/`
export const oidcScope =
  runtime.oidcScope ||
  (import.meta.env.VITE_OIDC_SCOPE as string) ||
  'openid profile email'
// Optional: same-origin by default, so a relative base is correct.
export const apiBaseUrl =
  runtime.apiBaseUrl ?? (import.meta.env.VITE_API_BASE_URL as string) ?? ''

// Required values must never silently default — a blank auth endpoint
// hides a misconfigured environment until it fails in subtle ways.
const REQUIRED: Record<string, string> = {
  oidcAuthority,
  oidcClientId,
}

export function requiredConfigErrors(): string[] {
  return Object.entries(REQUIRED)
    .filter(([, value]) => !value)
    .map(([name]) => name)
}

export function assertRequiredConfig(): void {
  const missing = requiredConfigErrors()
  if (missing.length > 0) {
    throw new Error(`Missing required runtime config: ${missing.join(', ')}`)
  }
}
