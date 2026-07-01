// Role administration singleton (editor-only surface). Lists known subjects
// and grants/revokes the editor role via /api/roles. All mutations go through
// the central api module; the server enforces authorization and bootstrap
// protection, so this composable stays a thin state holder.

import { ref } from 'vue'

import { api, ApiError } from '@/api'

export interface RoleRow {
  sub: string
  role: 'editor' | 'consumer'
  label: string
  updated: string
  source: 'bootstrap' | 'store'
}

const roles = ref<RoleRow[]>([])
const error = ref<string | null>(null)

export function useRoles() {
  async function fetchRoles(): Promise<void> {
    error.value = null
    try {
      roles.value = await api.get<RoleRow[]>('/api/roles')
    } catch (err) {
      error.value = messageOf(err)
    }
  }

  async function setRole(
    sub: string,
    role: 'editor' | 'consumer',
    label = ''
  ): Promise<void> {
    error.value = null
    try {
      await api.put(`/api/roles/${encodeURIComponent(sub)}`, { role, label })
      await fetchRoles()
    } catch (err) {
      error.value = messageOf(err)
      throw err
    }
  }

  async function removeRole(sub: string): Promise<void> {
    error.value = null
    try {
      await api.delete(`/api/roles/${encodeURIComponent(sub)}`)
      await fetchRoles()
    } catch (err) {
      error.value = messageOf(err)
      throw err
    }
  }

  return { roles, error, fetchRoles, setRole, removeRole }
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message
  }
  return err instanceof Error ? err.message : String(err)
}
