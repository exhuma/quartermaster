// Private-prompt state singleton. A private prompt is a standalone prompt
// visible only to its owner; these calls hit the owner-scoped
// /api/private-prompts routes. Any authenticated user may manage their own
// private prompts (ownership, not the editor role, is the gate), so this is
// available to consumers too. Mirrors usePrivateKits.ts.

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type { PromptDetail, PromptInfo } from '@/types/prompt'

const prompts = ref<PromptInfo[]>([])
const error = ref<string | null>(null)

export function usePrivatePrompts() {
  async function fetchPrivatePrompts(): Promise<void> {
    error.value = null
    try {
      prompts.value = await api.get<PromptInfo[]>('/api/private-prompts')
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  async function fetchPrivatePrompt(name: string): Promise<PromptDetail> {
    return api.get<PromptDetail>(
      `/api/private-prompts/${encodeURIComponent(name)}`
    )
  }

  async function createPrivatePrompt(
    name: string,
    title: string,
    description: string,
    body: string
  ): Promise<void> {
    error.value = null
    try {
      await api.post('/api/private-prompts', { name, title, description, body })
      await fetchPrivatePrompts()
    } catch (err) {
      error.value = messageOf(err)
      throw err
    }
  }

  async function updatePrivatePrompt(
    name: string,
    title: string,
    description: string,
    body: string
  ): Promise<void> {
    error.value = null
    try {
      await api.put(`/api/private-prompts/${encodeURIComponent(name)}`, {
        title,
        description,
        body,
      })
      await fetchPrivatePrompts()
    } catch (err) {
      error.value = messageOf(err)
      throw err
    }
  }

  async function deletePrivatePrompt(name: string): Promise<void> {
    error.value = null
    try {
      await api.delete(`/api/private-prompts/${encodeURIComponent(name)}`)
      await fetchPrivatePrompts()
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  return {
    prompts,
    error,
    fetchPrivatePrompts,
    fetchPrivatePrompt,
    createPrivatePrompt,
    updatePrivatePrompt,
    deletePrivatePrompt,
  }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
