import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import MarkdownView from '@/components/MarkdownView.vue'

function render(source: string | null | undefined) {
  return mount(MarkdownView, { props: { source } })
}

describe('MarkdownView', () => {
  it('renders block markdown (headings, lists, fenced code)', () => {
    const wrapper = render(
      '# Title\n\n- one\n- two\n\n```\ncode block\n```\n'
    )
    expect(wrapper.find('h1').text()).toBe('Title')
    const items = wrapper.findAll('li')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toBe('one')
    expect(wrapper.find('pre code').text()).toContain('code block')
  })

  it('escapes raw HTML rather than emitting it (html:false)', () => {
    const wrapper = render('Hello <script>alert(1)</script> world')
    // The tag is rendered as text, not injected as a live element.
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.html()).toContain('&lt;script&gt;')
  })

  it('opens links in a new tab with a safe rel', () => {
    const wrapper = render('[docs](https://example.com)')
    const link = wrapper.find('a')
    expect(link.attributes('href')).toBe('https://example.com')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
  })

  it('renders nothing for empty/nullish source', () => {
    expect(render('').text()).toBe('')
    expect(render(null).text()).toBe('')
    expect(render(undefined).text()).toBe('')
  })
})
