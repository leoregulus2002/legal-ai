import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { normalizeApiError } from '../../api/client'
import { fetchHealth } from './api'

export const useHealthStore = defineStore('health', () => {
  const status = ref<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const checkedAt = ref<Date | null>(null)
  const isLoading = computed(() => status.value === 'loading')

  async function refresh(): Promise<void> {
    if (isLoading.value) return
    status.value = 'loading'
    try {
      await fetchHealth()
      status.value = 'ok'
    } catch (error: unknown) {
      status.value = 'error'
      throw normalizeApiError(error)
    } finally {
      checkedAt.value = new Date()
    }
  }

  return { status, checkedAt, isLoading, refresh }
})
