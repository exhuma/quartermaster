import { createRouter, createWebHistory } from 'vue-router'
import type { RouteLocationNormalized } from 'vue-router'

import { userManager } from '@/auth/oidc'
import { devAuth } from '@/config'

// Protected routes require a live OIDC session. Store the target path as
// `state` so the callback can return the user there after login. Exported
// so it can be unit-tested without driving a full navigation.
export async function authGuard(to: RouteLocationNormalized): Promise<boolean> {
  if (to.meta.requiresAuth) {
    // Dev-only bypass: `devAuth` folds to literal `false` in production, so
    // this short-circuit is removed from the production build entirely.
    if (devAuth) {
      return true
    }
    const user = await userManager.getUser()
    if (!user || user.expired) {
      await userManager.signinRedirect({ state: to.fullPath })
      return false
    }
  }
  return true
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/LandingView.vue'),
      // Public: no `requiresAuth`, so the landing renders before sign-in.
    },
    {
      // The kit list. Path is `/catalog`, not `/kits`: the `/kits/*` prefix is
      // reserved by the backend MCP mount and 404s in the SPA history fallback
      // (server/app/webui.py). The route name stays `kits` so existing
      // `{ name: 'kits' }` links keep resolving here.
      path: '/catalog',
      name: 'kits',
      component: () => import('@/views/KitListView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/integration',
      name: 'integration',
      component: () => import('@/views/IntegrationView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/mount',
      name: 'mount',
      component: () => import('@/views/MountSetupView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/metrics',
      name: 'metrics',
      component: () => import('@/views/MetricsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/kit/:name',
      name: 'kit-detail',
      component: () => import('@/views/KitDetailView.vue'),
      props: true,
      meta: { requiresAuth: true },
    },
    {
      path: '/kit/:name/:version',
      name: 'kit-edit',
      component: () => import('@/views/KitEditorView.vue'),
      props: true,
      meta: { requiresAuth: true },
    },
    {
      path: '/private-kits',
      name: 'private-kits',
      component: () => import('@/views/PrivateKitsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('@/views/AdminUsersView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/auth/callback',
      name: 'auth-callback',
      component: () => import('@/views/AuthCallbackView.vue'),
    },
  ],
})

router.beforeEach(authGuard)

export default router
