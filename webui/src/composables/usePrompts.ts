// Prompt catalog state singleton. Lists and mutates prompts through the
// central api module; no business logic lives here (that is the server's
// job). Mirrors useKits.ts, but prompts have no versions/sections/
// applicability, so there is no create-time skeleton to build.

import { ref } from 'vue'

import { api, ApiError } from '@/api'
import type { PromptDetail, PromptInfo } from '@/types/prompt'
import { useLoading } from './useLoading'

const prompts = ref<PromptInfo[]>([])
const error = ref<string | null>(null)

const { withLoading } = useLoading()

export function usePrompts() {
  async function fetchPrompts(): Promise<void> {
    error.value = null
    try {
      prompts.value = await withLoading(api.get<PromptInfo[]>('/api/prompts'))
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  // Fetches the full detail (including body) for one prompt. The list
  // response omits body, so an edit dialog needs this before it can render.
  async function fetchPrompt(name: string): Promise<PromptDetail> {
    return withLoading(
      api.get<PromptDetail>(`/api/prompts/${encodeURIComponent(name)}`)
    )
  }

  async function createPrompt(
    name: string,
    title: string,
    description: string,
    body: string
  ): Promise<void> {
    error.value = null
    try {
      await withLoading(
        api.post('/api/prompts', { name, title, description, body })
      )
      await fetchPrompts()
    } catch (err) {
      error.value = messageOf(err)
      throw err
    }
  }

  async function updatePrompt(
    name: string,
    title: string,
    description: string,
    body: string
  ): Promise<void> {
    error.value = null
    try {
      await withLoading(
        api.put(`/api/prompts/${encodeURIComponent(name)}`, {
          title,
          description,
          body,
        })
      )
      await fetchPrompts()
    } catch (err) {
      error.value = messageOf(err)
      throw err
    }
  }

  async function deletePrompt(name: string): Promise<void> {
    error.value = null
    try {
      await withLoading(api.delete(`/api/prompts/${encodeURIComponent(name)}`))
      await fetchPrompts()
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  return {
    prompts,
    error,
    fetchPrompts,
    fetchPrompt,
    createPrompt,
    updatePrompt,
    deletePrompt,
  }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
