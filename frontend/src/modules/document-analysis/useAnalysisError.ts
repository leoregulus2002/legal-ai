import { normalizeApiError } from '../../api/client'
import { useErrorMessage } from '../../composables/useErrorMessage'
export function useAnalysisError(): (error: unknown) => void {
  const show = useErrorMessage()
  return (error: unknown): void => {
    show(normalizeApiError(error))
  }
}
