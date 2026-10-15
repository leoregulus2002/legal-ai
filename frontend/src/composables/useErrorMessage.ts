import { useMessage } from 'naive-ui'
import { normalizeApiError } from '../api/client'

const visibleMessages = new Set<string>()

export function useErrorMessage(): (error: unknown) => void {
  const message = useMessage()

  return (error: unknown): void => {
    const content = normalizeApiError(error).message
    if (visibleMessages.has(content)) return

    visibleMessages.add(content)
    message.error(content, {
      duration: 5000,
      closable: true,
      onAfterLeave: () => {
        visibleMessages.delete(content)
      },
    })
  }
}
