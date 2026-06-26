// Human descriptions for the kit-metadata editor fields, surfaced as (i)
// tooltips next to each input. Sourced from the authoritative dataclass
// docstrings in `server/app/kits.py` (KitApplicability / KitSection) and the
// V2 selector scoring model, plus the kit-authoring rules in CLAUDE.md /
// `.ai/rules.md`. Keep these in sync if those definitions change.

// applicability.json fields (kit discovery & ranking).
export const applicabilityHelp = {
  kit_type:
    "Kind of kit: 'module' (a single concern), 'stack' (a coordinated " +
    "baseline of modules), or 'release' (versioning/deployment guidance).",
  summary:
    'One short sentence describing what the kit is for, shown when listing ' +
    'and ranking kits. Aim for a single crisp line (≤ ~150 characters).',
  priority:
    'Base ranking score (higher is preferred). The selector starts from ' +
    'this value and adds weight for each project trait the kit matches.',
  domains:
    "Problem domains the kit targets (e.g. 'authentication', " +
    "'documentation'). A medium-weight match signal during ranking.",
  languages:
    'Programming languages the kit is associated with. The strongest ' +
    'positive match signal in ranking.',
  frameworks:
    "Frameworks the kit is associated with (e.g. 'fastapi', 'vue'). The " +
    'second-strongest match signal.',
  contexts:
    "Project contexts where the kit is useful (e.g. 'backend', " +
    "'frontend'). A weak match signal.",
  requires:
    'Hard requirements per trait category. A project missing any of these ' +
    'makes the kit ineligible (or uncertain when the trait is simply ' +
    'unknown).',
  excludes:
    'Hard exclusions per trait category. If the project has any of these ' +
    'traits, the kit is ruled out entirely.',
  optional_signals:
    'Extra weak signals that nudge ranking up when present, but never gate ' +
    'eligibility.',
  related_kits:
    'Other kit names commonly loaded together with this one; surfaced as ' +
    'suggestions.',
} as const

// index.toml section fields (instruction structure).
export const sectionHelp = {
  id:
    "Stable section identifier — the Markdown file's stem (e.g. " +
    "'invariant'). Used in URLs and to request a single section. Lowercase " +
    'words joined by hyphens; fixed after creation.',
  title: 'Human-readable section heading, shown in the outline and the list.',
  gloss:
    'One-line summary shown in the kit outline. Write a self-contained ' +
    'sentence — not a cut of the body — and keep it to one line ' +
    '(≤ ~100 characters).',
  always_load:
    'When on, this section holds core invariants an agent should always ' +
    'pull into context (e.g. prohibited patterns), even when not requested.',
  body: "The section's Markdown content — the actual agent-facing guidance.",
} as const
