import { ref } from 'vue'
import { defineStore } from 'pinia'
import { publicLawApi } from './api'
import type { PublicLawOptions } from './types'

export const usePublicLawOptionsStore = defineStore('public-law-options', () => {
  const options = ref<PublicLawOptions>()
  const optionsLoading = ref(false)
  let pending: Promise<void> | undefined

  function loadOptions(): Promise<void> {
    if (options.value) return Promise.resolve()
    if (pending) return pending
    optionsLoading.value = true
    pending = publicLawApi
      .options()
      .then((value) => {
        options.value = value
      })
      .finally(() => {
        optionsLoading.value = false
        pending = undefined
      })
    return pending
  }

  return { options, optionsLoading, loadOptions }
})
