// Dev-only auth bypass (module-dev-auth-bypass).
//
// This module is imported ONLY from inside the compile-time `devAuth`
// branch in main.ts, so a production build dead-code-eliminates it — none
// of this code (nor the /auth/dev path it calls) ships to production.
//
// It fetches a self-minted HS256 dev token from the server's dev-login
// endpoint and wires it into the api module's TokenProvider seam, so the
// app authenticates locally without an IdP.

import { setTokenProvider } from '@/api'
import { useAuth } from '@/composables/useAuth'

export async function setupDevAuth(): Promise<void> {
  const response = await fetch('/auth/dev/token')
  if (!response.ok) {
    throw new Error(
      `Dev auth unavailable (HTTP ${response.status}). Set ` +
        'DEV_AUTH_ENABLED and DEV_SHARED_SECRET on the server.',
    )
  }
  const data = (await response.json()) as { access_token: string }
  setTokenProvider({ getToken: () => data.access_token })
  useAuth().enterDevSession('dev')
}
