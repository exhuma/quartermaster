import { beforeAll, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

import FieldHelp from '@/components/FieldHelp.vue'

// Vuetify's display composable reads matchMedia / ResizeObserver, which jsdom
// does not implement. Stub them so components mount.
beforeAll(() => {
  globalThis.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  })) as unknown as typeof globalThis.matchMedia
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
})

const vuetify = createVuetify({ components, directives })

function mountFieldHelp(text: string) {
  return mount(FieldHelp, {
    props: { text },
    global: { plugins: [vuetify] },
    attachTo: document.body,
  })
}

describe('FieldHelp', () => {
  it('renders an info icon that activates a tooltip carrying the text', () => {
    const text = 'What this field is for.'
    const wrapper = mountFieldHelp(text)
    // The hoverable activator: an icon (not buried in a pointer-events:none
    // field label) exposing the text for assistive tech.
    const icon = wrapper.find('[role="img"]')
    expect(icon.exists()).toBe(true)
    expect(icon.attributes('aria-label')).toBe(text)
    // The tooltip is wired with the same description as its content.
    expect(document.body.textContent).toContain(text)
    wrapper.unmount()
  })
})
