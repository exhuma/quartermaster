// Re-authentication loop guard (module-auth-oidc-vue: reauthentication loop
// guard). A 401 normally means an expired session, which one silent redirect
// to the IdP resolves. But a token can be cryptographically valid yet still
// rejected by the resource server — wrong audience, issuer, or scope. In that
// case re-authenticating yields the *same* rejected token, so an unguarded
// "401 → signinRedirect" handler loops forever. This circuit breaker bounds
// re-auth to a single redirect per failure episode and surfaces a clear error
// instead of looping.

import { ref } from 'vue'

import { userManager } from '@/auth/oidc'

// Survives the full-page redirect round-trip so we can tell a fresh sign-in
// that still 401s (config mismatch) from a first, legitimate expiry.
const ATTEMPT_KEY = 'reauthAttempts'

// Reactive error surfaced by the app shell (App.vue) as a blocking dialog.
export const authError = ref<string | null>(null)

// Collapses the burst of parallel 401s a single page load can produce into one
// redirect. Reset on every fresh page load (module reload), which is exactly
// when we want to allow another attempt.
let redirectInFlight = false

const AUTH_ERROR_MESSAGE =
  'Your session could not be authenticated. This usually means a ' +
  'configuration mismatch (for example an incorrect token audience). ' +
  'Sign in again, or contact an administrator if it persists.'

function readAttempts(): number {
  return Number(sessionStorage.getItem(ATTEMPT_KEY) ?? '0')
}

// Called on every 401 from the central API seam. First failure → one redirect;
// a second failure (the redirect produced a still-rejected token) trips the
// breaker and shows the error instead of redirecting again.
export function handleUnauthorized(): void {
  if (redirectInFlight) {
    return
  }
  if (readAttempts() >= 1) {
    sessionStorage.removeItem(ATTEMPT_KEY)
    authError.value = AUTH_ERROR_MESSAGE
    return
  }
  sessionStorage.setItem(ATTEMPT_KEY, String(readAttempts() + 1))
  redirectInFlight = true
  void userManager.signinRedirect({ state: window.location.pathname })
}

// Called on every successful API response. A single redirect resolved a real
// expiry, so clear the counter and let future expiries redirect normally.
export function notifyAuthSuccess(): void {
  sessionStorage.removeItem(ATTEMPT_KEY)
}

// "Sign in again" action from the error dialog: reset the breaker and retry.
export function retryAuthentication(): void {
  authError.value = null
  sessionStorage.removeItem(ATTEMPT_KEY)
  redirectInFlight = true
  void userManager.signinRedirect({ state: window.location.pathname })
}

// Test-only hook to reset module state between cases.
export function _resetReauthGuard(): void {
  authError.value = null
  redirectInFlight = false
  sessionStorage.removeItem(ATTEMPT_KEY)
}
