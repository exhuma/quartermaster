// Vuetify instance + theme. All component colours reference these theme
// tokens — never hex/rgb literals in components (module-vue-vuetify:
// vuetify-theming).
//
// The default theme is the "Tactical Provisioning System" — a dark
// "Mission Navy + Brass Gold" palette. Beyond Vuetify's standard tokens it
// registers the Material-style surface-container / outline ramp as custom
// colours, so components can reference bg-surface-container-high,
// text-on-surface-variant, and (via the --v-theme-* CSS vars) blueprint
// borders in `outline-variant`.

import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'

import { createVuetify } from 'vuetify'

// Resolve the theme to show on first paint, before any component mounts, so
// there is no flash of the wrong scheme. Honours a persisted user choice
// (qm-theme-mode) and otherwise follows the OS `prefers-color-scheme`. The
// live toggle + system-change listening are handled by useThemeMode; this is
// only the initial value. Kept in sync with THEME_STORAGE_KEY there.
export function initialThemeName(): 'instructionsDark' | 'instructionsLight' {
  try {
    const stored = window.localStorage?.getItem('qm-theme-mode')
    if (stored === 'light') return 'instructionsLight'
    if (stored === 'dark') return 'instructionsDark'
  } catch {
    // localStorage can throw (privacy mode); fall through to system default.
  }
  const prefersDark =
    window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true
  return prefersDark ? 'instructionsDark' : 'instructionsLight'
}

export default createVuetify({
  theme: {
    defaultTheme: initialThemeName(),
    themes: {
      // Tactical navy/brass. This is the brand theme and the app default.
      instructionsDark: {
        dark: true,
        colors: {
          // Brass — the single high-value accent (CTAs, active state, brand).
          primary: '#e9c176',
          'on-primary': '#412d00',
          'primary-container': '#c5a059',
          'on-primary-container': '#412d00',
          // Technical blue — secondary information and connected/online state.
          secondary: '#b7c8dd',
          'on-secondary': '#223242',
          'secondary-container': '#3b4a5c',
          'on-secondary-container': '#a9bacf',
          // Mission Navy canvas + the card base one step above it.
          background: '#051424',
          'on-background': '#d4e4fa',
          surface: '#122131',
          'on-surface': '#d4e4fa',
          // Status colours, desaturated to sit calmly on navy.
          error: '#ffb4ab',
          'on-error': '#690005',
          info: '#b5c8df',
          'on-info': '#203243',
          success: '#8cc99a',
          'on-success': '#0c2914',
          warning: '#e0a458',
          'on-warning': '#3a2600',
          // --- Custom ramp (generates bg-*/text-* utilities + CSS vars) ---
          'surface-bright': '#2c3a4c',
          'surface-container-lowest': '#010f1f',
          'surface-container-low': '#0d1c2d',
          'surface-container': '#122131',
          'surface-container-high': '#1c2b3c',
          'surface-container-highest': '#273647',
          'on-surface-variant': '#d1c5b4',
          outline: '#9a8f80',
          'outline-variant': '#4e4639',
        },
      },
      // Tactical light variant — the same brand seed (#c5a059) rendered by
      // Stitch's colour system in LIGHT mode: a paper-white canvas with cool
      // blue-grey surfaces and a darker brass primary that reads on white.
      // Mirrors the dark token set so components work unchanged in both.
      instructionsLight: {
        dark: false,
        colors: {
          // Brass, darkened for contrast on white; the gold lives in -container.
          primary: '#775a19',
          'on-primary': '#ffffff',
          'primary-container': '#c5a059',
          'on-primary-container': '#4e3700',
          secondary: '#506072',
          'on-secondary': '#ffffff',
          'secondary-container': '#d3e4fa',
          'on-secondary-container': '#566678',
          // Paper canvas + a faintly blue elevated card base.
          background: '#f8f9ff',
          'on-background': '#0d1c2d',
          surface: '#e5efff',
          'on-surface': '#0d1c2d',
          // Status colours for a light surface.
          error: '#ba1a1a',
          'on-error': '#ffffff',
          info: '#4e6073',
          'on-info': '#ffffff',
          success: '#2e6b3e',
          'on-success': '#ffffff',
          warning: '#8a5300',
          'on-warning': '#ffffff',
          // --- Custom ramp (mirrors the dark theme's token names) ---
          'surface-bright': '#ffffff',
          'surface-container-lowest': '#ffffff',
          'surface-container-low': '#eef4ff',
          'surface-container': '#e5efff',
          'surface-container-high': '#dbe9ff',
          'surface-container-highest': '#d4e4fa',
          'on-surface-variant': '#4e4639',
          outline: '#7f7667',
          'outline-variant': '#d1c5b4',
        },
      },
    },
  },
  // Machined, blueprint-cased feel: small radii, bordered cards.
  defaults: {
    VCard: { rounded: 'lg' },
    VBtn: { rounded: 'sm' },
    VChip: { rounded: 'sm' },
    VTextField: { rounded: 'sm' },
  },
})
