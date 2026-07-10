import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import StatusChip from '@/components/StatusChip.vue'

// StatusChip is a plain presentational span (no Vuetify components), so it
// mounts without the Vuetify plugin. It maps a semantic status onto a theme
// colour token, surfaced as the `--chip-color` CSS variable.
function mountChip(props: { label: string; status?: string }) {
  return mount(StatusChip, { props })
}

function chipColorVar(wrapper: ReturnType<typeof mountChip>): string {
  return wrapper.find('.status-chip').attributes('style') ?? ''
}

describe('StatusChip', () => {
  it('renders the label text', () => {
    const wrapper = mountChip({ label: 'core' })
    expect(wrapper.text()).toContain('core')
  })

  it.each([
    ['active', 'success'],
    ['online', 'success'],
    ['archived', 'on-surface-variant'],
    ['error', 'error'],
    ['warning', 'warning'],
  ])('maps status "%s" onto the %s theme token', (status, token) => {
    const wrapper = mountChip({ label: 'x', status })
    expect(chipColorVar(wrapper)).toContain(`--v-theme-${token}`)
  })

  it('passes an unknown status through as its own theme token', () => {
    const wrapper = mountChip({ label: 'x', status: 'primary' })
    expect(chipColorVar(wrapper)).toContain('--v-theme-primary')
  })

  it('defaults to a neutral token when no status is given', () => {
    const wrapper = mountChip({ label: 'x' })
    expect(chipColorVar(wrapper)).toContain('--v-theme-on-surface-variant')
  })
})
