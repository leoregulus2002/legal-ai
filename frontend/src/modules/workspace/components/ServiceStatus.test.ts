import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ServiceStatus from './ServiceStatus.vue'

describe('ServiceStatus', () => {
  it('renders real state and emits refresh', async () => {
    const wrapper = mount(ServiceStatus, { props: { status: 'ok' } })
    expect(wrapper.text()).toContain('服务正常')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
  })
  it('shows unavailable status without rendering error details in the page', () => {
    const wrapper = mount(ServiceStatus, { props: { status: 'error' } })
    expect(wrapper.text()).toContain('服务不可用')
    expect(wrapper.find('.status-error').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('服务正常')
  })
})
