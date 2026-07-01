// Canonical TypeScript types for business objects crossing the API
// boundary (module-vue-vuetify: business-object-typing).

export interface KitInfo {
  name: string
  description: string
  versions: string[]
  latest_version: string
  source_layer: string | null
}

export interface KitDetail {
  name: string
  versions: string[]
  latest_version: string
  applicability: Record<string, unknown>
}

export interface SectionMeta {
  id: string
  title: string
  gloss: string
  always_load: boolean
  bytes: number
}

export interface KitOutline {
  name: string
  version: string
  summary: string
  sections: SectionMeta[]
}

export interface SectionContent {
  id: string
  title: string
  gloss: string
  always_load: boolean
  body: string
}

export interface TraitMap {
  languages: string[]
  frameworks: string[]
  capabilities: string[]
  contexts: string[]
}

export interface Applicability {
  kit_type: string
  summary: string
  domains: string[]
  languages: string[]
  frameworks: string[]
  contexts: string[]
  requires: TraitMap
  excludes: TraitMap
  optional_signals: string[]
  related_kits: string[]
  priority: number
}

export interface TraitVocab {
  trait_keys: string[]
  kit_types: string[]
  languages: string[]
  frameworks: string[]
  capabilities: string[]
  contexts: string[]
  domains: string[]
  optional_signals: string[]
}

export interface VersionCompare {
  changes: { version: string; summary: string }[]
  user_facing_warning: boolean
}

export interface AppToken {
  id: string
  user: string
  label: string
  created: string
}

export interface MintedToken extends AppToken {
  token: string
}

export interface IntegrationInfo {
  server_origin: string
  mcp_url: string
  keycloak_issuer: string
  keycloak_realm: string
  webui_client_id: string
  oauth_scopes: string[]
  oauth_metadata_url: string
  authorization_endpoint: string
  token_endpoint: string
  copilot_auth_enabled: boolean
  api_media_type: string
  client_registration_url: string
}
