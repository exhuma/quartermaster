import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// Feed the view controlled data via the mocked composable rather than a real
// network fetch.
vi.mock('@/composables/useChangelog')

import ChangelogView from '@/views/ChangelogView.vue'
import { useChangelog } from '@/composables/useChangelog'

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

function entry(overrides: Record<string, unknown> = {}) {
  return {
    subject: '[MCP] A tool changed',
    type: 'added',
    detail: 'Now uses `resolve_kits`.',
    is_highlight: false,
    is_internal: false,
    issue_ids: [],
    issue_urls: [],
    ...overrides,
  }
}

const SAMPLE = [
  {
    logs: [
      entry({
        subject: '[MCP] Big new behaviour',
        is_highlight: true,
        detail: 'Details with `code`.',
      }),
      entry({ subject: '[UI] A screen changed', type: 'changed', detail: '' }),
    ],
    meta: { version: '2026.7.11', date: null, notes: '' },
  },
  {
    logs: [
      entry({
        subject: '[API] Endpoint returns 204',
        type: 'changed',
        detail: '',
      }),
    ],
    meta: { version: '2026.6.26', date: '2026-06-26', notes: 'A note.' },
  },
]

function mockChangelog(data = SAMPLE) {
  vi.mocked(useChangelog).mockReturnValue({
    releases: ref(data),
    error: ref(null),
    loaded: ref(true),
    fetchChangelog: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useChangelog>)
}

function mountView() {
  return mount(ChangelogView, {
    global: { plugins: [vuetify] },
    attachTo: document.body,
  })
}

describe('ChangelogView', () => {
  it('renders releases with an Unreleased group and a dated version', async () => {
    mockChangelog()
    const wrapper = mountView()
    const text = wrapper.text()
    expect(text).toContain('Unreleased')
    expect(text).toContain('2026.6.26')
    expect(text).toContain('Big new behaviour')
    // The audience marker is stripped from the displayed subject.
    expect(text).not.toContain('[MCP]')
    // Inline markdown renders code spans.
    expect(wrapper.html()).toContain('<code>code</code>')
    wrapper.unmount()
  })

  it('filters entries by audience', async () => {
    mockChangelog()
    const wrapper = mountView()
    // Click the "REST API" filter chip.
    const chip = wrapper
      .findAll('.v-chip')
      .find((c) => c.text().includes('REST API'))
    expect(chip).toBeTruthy()
    await chip!.trigger('click')
    const text = wrapper.text()
    expect(text).toContain('Endpoint returns 204')
    expect(text).not.toContain('Big new behaviour')
    expect(text).not.toContain('A screen changed')
    wrapper.unmount()
  })
})
