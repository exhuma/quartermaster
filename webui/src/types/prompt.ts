// Canonical TypeScript types for the prompts catalog, the sibling of the
// kits catalog (module-vue-vuetify: business-object-typing). A prompt is a
// single unversioned Markdown file — no sections, no versions, no
// applicability manifest, unlike a kit.

export interface PromptInfo {
  name: string
  title: string
  description: string
  source_layer: string | null
  // False when the prompt's owning layer is read-only for the REST surface:
  // the web UI hides its edit affordances.
  editable: boolean
  // Set when the prompt file is malformed: listed but flagged so it can be
  // surfaced and fixed (see app/prompt_catalog.py list_all_prompts).
  broken?: boolean
  error?: string | null
}

export interface PromptDetail extends PromptInfo {
  body: string
}
