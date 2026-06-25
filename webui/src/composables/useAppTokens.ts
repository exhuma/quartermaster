// WebDAV app-token operations: mint (plaintext shown once), list, revoke.

import { ref } from 'vue'

import { api } from '@/api'
import type { AppToken, MintedToken } from '@/types/kit'
import { useLoading } from './useLoading'

const tokens = ref<AppToken[]>([])

const { withLoading } = useLoading()

export function useAppTokens() {
  async function fetchTokens(): Promise<void> {
    tokens.value = await withLoading(api.get<AppToken[]>('/api/app-tokens'))
  }

  async function mint(label: string): Promise<MintedToken> {
    const minted = await withLoading(
      api.post<MintedToken>('/api/app-tokens', { label }),
    )
    await fetchTokens()
    return minted
  }

  async function revoke(id: string): Promise<void> {
    await withLoading(api.delete(`/api/app-tokens/${encodeURIComponent(id)}`))
    await fetchTokens()
  }

  return { tokens, fetchTokens, mint, revoke }
}
