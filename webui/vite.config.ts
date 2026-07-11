import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

// The dev server proxies the data surfaces to the FastAPI backend so
// `npm run dev` talks to a locally-running server. In production the SPA
// is served by that same server, so these paths are same-origin.
export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/kits': 'http://localhost:8000',
      // Public changelog JSON. Served by the FastAPI backend (rendered from
      // changelog.in into app/assets/text/changelog.json), NOT a static file in
      // webui/public — so it must be proxied in dev too, otherwise the SPA's
      // same-origin fetch would resolve against Vite's dev server and 404.
      '/changelog.json': 'http://localhost:8000',
      // Dev-only auth bypass endpoint (only mounted when the server has
      // DEV_AUTH_ENABLED). Scoped to /auth/dev so it never shadows the
      // SPA's own /auth/callback client route.
      '/auth/dev': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.ts'],
    // Process Vuetify through Vite so its `.css` side-effect imports resolve
    // when mounting components in jsdom.
    server: { deps: { inline: ['vuetify'] } },
  },
})
