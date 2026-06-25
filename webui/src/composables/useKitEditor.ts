// Kit editor operations. Thin wrappers over the central api module so the
// detail/editor views stay declarative; validation errors surface as the
// ApiError thrown by the api module (the server is the source of truth).
// The trait vocabulary is global, so it is cached in a module-scope ref.

import { ref } from 'vue'

import { api } from '@/api'
import type {
  Applicability,
  KitDetail,
  KitOutline,
  SectionContent,
  TraitVocab,
  VersionCompare,
} from '@/types/kit'
import { useLoading } from './useLoading'

const traits = ref<TraitVocab | null>(null)

const { withLoading } = useLoading()

function enc(part: string): string {
  return encodeURIComponent(part)
}

export function useKitEditor() {
  function getDetail(name: string): Promise<KitDetail> {
    return withLoading(api.get<KitDetail>(`/api/kits/${enc(name)}`))
  }

  function getApplicability(name: string): Promise<Applicability> {
    return withLoading(
      api.get<Applicability>(`/api/kits/${enc(name)}/applicability`),
    )
  }

  function saveApplicability(
    name: string,
    manifest: Applicability,
  ): Promise<Applicability> {
    return withLoading(
      api.put<Applicability>(
        `/api/kits/${enc(name)}/applicability`,
        manifest,
      ),
    )
  }

  function getOutline(name: string, version: string): Promise<KitOutline> {
    return withLoading(
      api.get<KitOutline>(
        `/api/kits/${enc(name)}/versions/${enc(version)}/outline`,
      ),
    )
  }

  function getSection(
    name: string,
    version: string,
    id: string,
  ): Promise<SectionContent> {
    return withLoading(
      api.get<SectionContent>(
        `/api/kits/${enc(name)}/versions/${enc(version)}/sections/${enc(id)}`,
      ),
    )
  }

  function saveSection(
    name: string,
    version: string,
    id: string,
    payload: Omit<SectionContent, 'id'>,
  ): Promise<SectionContent> {
    return withLoading(
      api.put<SectionContent>(
        `/api/kits/${enc(name)}/versions/${enc(version)}/sections/${enc(id)}`,
        payload,
      ),
    )
  }

  function deleteSection(
    name: string,
    version: string,
    id: string,
  ): Promise<string[]> {
    return withLoading(
      api.delete<string[]>(
        `/api/kits/${enc(name)}/versions/${enc(version)}/sections/${enc(id)}`,
      ),
    )
  }

  function deleteVersion(name: string, version: string): Promise<string[]> {
    return withLoading(
      api.delete<string[]>(
        `/api/kits/${enc(name)}/versions/${enc(version)}`,
      ),
    )
  }

  function getChangelog(name: string): Promise<{ changelog: string }> {
    return withLoading(
      api.get<{ changelog: string }>(`/api/kits/${enc(name)}/changelog`),
    )
  }

  function compareVersions(
    name: string,
    from: string,
    to: string,
  ): Promise<VersionCompare> {
    const query = `from=${enc(from)}&to=${enc(to)}`
    return withLoading(
      api.get<VersionCompare>(`/api/kits/${enc(name)}/compare?${query}`),
    )
  }

  async function loadTraits(): Promise<TraitVocab> {
    if (!traits.value) {
      traits.value = await withLoading(api.get<TraitVocab>('/api/traits'))
    }
    return traits.value
  }

  return {
    traits,
    getDetail,
    getApplicability,
    saveApplicability,
    getOutline,
    getSection,
    saveSection,
    deleteSection,
    deleteVersion,
    getChangelog,
    compareVersions,
    loadTraits,
  }
}
