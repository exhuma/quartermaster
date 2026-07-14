// Authentication state singleton (module-vue-vuetify: state-management).
// Wraps the oidc-client-ts UserManager; the module-scope refs are the
// single source of truth for the current user across the app.

import { computed, ref } from 'vue'
import type { User } from 'oidc-client-ts'

import { userManager } from '@/auth/oidc'
import { authDisabled } from '@/config'

// Label shown for the single synthetic caller in auth-less mode.
const ANONYMOUS_LABEL = 'local'

const user = ref<User | null>(null)
const ready = ref(false)
// Dev-only bypass session (module-dev-auth-bypass). In production this is
// never set — the dev-login helper that sets it is dead-code-eliminated —
// so it is inert dead weight, not a bypass on its own.
const devName = ref<string | null>(null)

export function useAuth() {
  // Auth-less mode: the app is always "authenticated" as the synthetic local
  // caller. No OIDC session, no expiry, no token — the backend enforces nothing.
  const isAuthenticated = computed(
    () =>
      authDisabled || !!devName.value || (!!user.value && !user.value.expired)
  )
  const displayName = computed(() =>
    authDisabled
      ? ANONYMOUS_LABEL
      : (devName.value ??
        user.value?.profile.name ??
        user.value?.profile.email ??
        '')
  )

  function enterDevSession(name: string): void {
    devName.value = name
    ready.value = true
  }

  async function refresh(): Promise<void> {
    if (authDisabled || devName.value) {
      // No OIDC session to load in auth-less/dev mode; mark ready immediately.
      ready.value = true
      return
    }
    user.value = await userManager.getUser()
    ready.value = true
  }

  async function login(returnTo?: string): Promise<void> {
    // No IdP to redirect to when auth is disabled; a stray call is a no-op.
    if (authDisabled) {
      return
    }
    await userManager.signinRedirect({
      state: returnTo ?? window.location.pathname,
    })
  }

  async function logout(): Promise<void> {
    if (authDisabled || devName.value) {
      devName.value = null
      return
    }
    await userManager.signoutRedirect()
  }

  return {
    user,
    ready,
    isAuthenticated,
    displayName,
    enterDevSession,
    refresh,
    login,
    logout,
  }
}
