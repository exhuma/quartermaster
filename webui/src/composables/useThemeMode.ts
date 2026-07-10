// Colour-scheme preference singleton. Three user-facing modes:
//   'system' (default) — follow the OS `prefers-color-scheme`, live;
//   'light' / 'dark'   — an explicit, persisted override.
// The chosen mode is stored in localStorage so it survives reloads; the
// initial paint is resolved separately in plugins/vuetify.ts (initialThemeName)
// from the same key, so there is no flash of the wrong scheme.
//
// This is a plain UI preference, deliberately client-side — not a
// security-sensitive toggle, so it does not belong in runtime config
// (module-runtime-config-spa).

import { computed, ref } from 'vue'
import { useTheme } from 'vuetify'

export type ThemeMode = 'system' | 'light' | 'dark'

// Must match the key read by initialThemeName() in plugins/vuetify.ts.
export const THEME_STORAGE_KEY = 'qm-theme-mode'

const DARK = 'instructionsDark'
const LIGHT = 'instructionsLight'

function readStoredMode(): ThemeMode {
  try {
    const v = window.localStorage?.getItem(THEME_STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') {
      return v
    }
  } catch {
    // localStorage may throw (privacy mode); fall back to following the OS.
  }
  return 'system'
}

// Module-scoped so every caller shares one source of truth (and one media
// listener). The ref seeds from storage at import time.
const mode = ref<ThemeMode>(readStoredMode())
const prefersDark = ref(
  window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true
)

// Register the OS-change listener exactly once, regardless of how many
// components use the composable.
let mediaBound = false
function bindMediaListener(): void {
  if (mediaBound) {
    return
  }
  mediaBound = true
  const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
  mq?.addEventListener?.('change', (e) => {
    prefersDark.value = e.matches
  })
}

// The resolved Vuetify theme name for a mode + current OS preference.
function resolve(m: ThemeMode): typeof DARK | typeof LIGHT {
  const dark = m === 'dark' || (m === 'system' && prefersDark.value)
  return dark ? DARK : LIGHT
}

export function useThemeMode() {
  const theme = useTheme()
  bindMediaListener()

  const effectiveName = computed(() => resolve(mode.value))
  const isDark = computed(() => effectiveName.value === DARK)

  // Keep Vuetify in sync with the resolved name (covers a live OS change while
  // in 'system' mode, and re-application after mount). Guarded so we never try
  // to switch to a theme the current Vuetify instance hasn't registered (e.g.
  // a bare test instance) — that would leave `current` undefined.
  function apply(): void {
    const target = effectiveName.value
    if (theme.name.value !== target && theme.themes.value[target]) {
      void theme.change(target)
    }
  }

  function setMode(next: ThemeMode): void {
    mode.value = next
    try {
      window.localStorage?.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // Non-fatal: the preference just won't persist across reloads.
    }
    apply()
  }

  return { mode, isDark, effectiveName, setMode, apply }
}
