// Integration metadata singleton: how to connect a coding agent to the
// MCP, plus the data the client-registration UI needs.

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type { IntegrationInfo } from '@/types/kit'
import { useLoading } from './useLoading'

const info = ref<IntegrationInfo | null>(null)
const error = ref<string | null>(null)

const { withLoading } = useLoading()

export function useIntegration() {
  async function fetchInfo(): Promise<void> {
    error.value = null
    try {
      info.value = await withLoading(
        api.get<IntegrationInfo>('/api/integration')
      )
    } catch (err) {
      error.value =
        err instanceof ApiError || err instanceof Error
          ? err.message
          : String(err)
    }
  }

  async function registerUserAgent(
    userAgent: string,
    label: string
  ): Promise<void> {
    await withLoading(
      api.post('/api/clients', { user_agent: userAgent, label })
    )
  }

  return { info, error, fetchInfo, registerUserAgent }
}
