import { createApp } from 'vue'

import './styles/app.css'
import App from './App.vue'
import router from './router'
import vuetify from './plugins/vuetify'
import { assertRequiredConfig, authDisabled, devAuth } from './config'
import {
  setAuthSuccessHandler,
  setTokenProvider,
  setUnauthorizedHandler,
} from './api'
import { userManager } from './auth/oidc'
import { handleUnauthorized, notifyAuthSuccess } from './auth/reauthGuard'

async function bootstrap(): Promise<void> {
  if (authDisabled) {
    // Auth-less mode: no OIDC, no token, no re-auth loop. Send no bearer token
    // (the backend enforces nothing) and neutralize the 401 handler so a stray
    // 401 never redirects to a nonexistent IdP.
    setTokenProvider({ getToken: () => null })
    setUnauthorizedHandler(() => {})
  } else if (devAuth) {
    // Dev-only bypass. The dynamic import sits inside a branch gated by the
    // compile-time `devAuth` literal, so a production build removes this
    // branch and never bundles the dev-login helper.
    const { setupDevAuth } = await import('./auth/devAuth')
    await setupDevAuth()
  } else {
    // Production path: fail loudly on a misconfigured environment, then wire
    // oidc-client-ts into the api module's TokenProvider seam. The re-auth
    // loop guard (handleUnauthorized) redirects to Keycloak on a 401 but trips
    // a circuit breaker if a fresh token is still rejected, so a misconfigured
    // audience/issuer surfaces an error instead of looping.
    assertRequiredConfig()
    setTokenProvider({
      getToken: async () => {
        const user = await userManager.getUser()
        return user?.access_token ?? null
      },
    })
    setUnauthorizedHandler(handleUnauthorized)
    setAuthSuccessHandler(notifyAuthSuccess)
  }

  createApp(App).use(vuetify).use(router).mount('#app')
}

void bootstrap()
