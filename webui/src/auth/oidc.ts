// oidc-client-ts UserManager — the only OIDC library (module-auth-oidc-vue).
// Public client, authorization-code + PKCE, against the same Keycloak realm
// the server validates tokens from. Values come from the typed runtime
// config module (never read directly from env/global here).

import { UserManager, WebStorageStateStore } from 'oidc-client-ts'

import {
  oidcAuthority,
  oidcClientId,
  oidcPostLogoutUri,
  oidcRedirectUri,
  oidcScope,
} from '@/config'

// Token storage: sessionStorage — survives an in-tab reload but is not
// shared across tabs and is cleared when the tab closes. Trade-offs are
// recorded in contract.md.
// Benign fallbacks so construction never throws when OIDC is unconfigured
// in the dev-auth bypass (where the real IdP is intentionally absent). In
// production these are always set (config asserts them at boot) and the
// fallbacks are never used.
export const userManager = new UserManager({
  authority: oidcAuthority || window.location.origin,
  client_id: oidcClientId || 'oidc-unconfigured',
  redirect_uri: oidcRedirectUri,
  post_logout_redirect_uri: oidcPostLogoutUri,
  scope: oidcScope,
  response_type: 'code',
  automaticSilentRenew: true,
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
})
