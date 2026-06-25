import { createRouter, createWebHistory } from 'vue-router'
import type { RouteLocationNormalized } from 'vue-router'

import { userManager } from '@/auth/oidc'
import { devAuth } from '@/config'

// Protected routes require a live OIDC session. Store the target path as
// `state` so the callback can return the user there after login. Exported
// so it can be unit-tested without driving a full navigation.
export async function authGuard(
  to: RouteLocationNormalized,
): Promise<boolean> {
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
      path: '/auth/callback',
      name: 'auth-callback',
      component: () => import('@/views/AuthCallbackView.vue'),
    },
  ],
})

router.beforeEach(authGuard)

export default router
