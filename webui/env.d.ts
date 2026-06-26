/// <reference types="vite/client" />

// Build-time (local-dev) fallback values. In production these are unset
// and the runtime `window.__APP_CONFIG__` global (served as /config.js)
// supplies the values instead — see src/config.ts.
interface ImportMetaEnv {
  readonly VITE_OIDC_AUTHORITY?: string
  readonly VITE_OIDC_CLIENT_ID?: string
  readonly VITE_OIDC_REDIRECT_URI?: string
  readonly VITE_OIDC_POST_LOGOUT_URI?: string
  readonly VITE_OIDC_SCOPE?: string
  readonly VITE_API_BASE_URL?: string
  // Dev-only auth bypass opt-in (module-dev-auth-bypass). Effective only
  // together with the build-time `import.meta.env.DEV` flag.
  readonly VITE_DEV_AUTH?: string
  // Build identity, baked at image-build time (module-github-link,
  // module-release-metadata). All optional — each governed UI element is
  // hidden when its variable is absent.
  readonly VITE_GITHUB_REPO_URL?: string
  readonly VITE_APP_COMMIT?: string
  readonly VITE_APP_BUILD_TIME?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
