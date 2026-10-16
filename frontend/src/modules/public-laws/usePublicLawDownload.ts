import { onUnmounted, ref } from 'vue'
import { useErrorMessage } from '../../composables/useErrorMessage'
import { publicLawApi } from './api'
import type { PublicLaw, PublicLawFormat } from './types'

export function usePublicLawDownload() {
  const downloadingId = ref<string>()
  const showError = useErrorMessage()
  let controller: AbortController | undefined
  let alive = true

  async function download(law: PublicLaw, format: PublicLawFormat = 'docx'): Promise<void> {
    if (downloadingId.value) return
    downloadingId.value = law.id
    controller = new AbortController()
    try {
      const blob = await publicLawApi.download(law, format, controller.signal)
      if (!alive) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${law.title.replace(/[\\/:*?"<>|\p{Cc}]/gu, '_')}.${format}`
      document.body.append(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error: unknown) {
      if (alive) showError(error)
    } finally {
      if (alive) downloadingId.value = undefined
    }
  }

  onUnmounted(() => {
    alive = false
    controller?.abort()
  })

  return { downloadingId, download }
}
