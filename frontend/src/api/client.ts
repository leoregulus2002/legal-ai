import axios from 'axios'
import type { AxiosInstance } from 'axios'

export type ApiErrorKind = 'timeout' | 'network' | 'http' | 'unknown'

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly kind: ApiErrorKind,
    public readonly status: number | undefined = undefined,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function serverMessage(data: unknown): string | undefined {
  if (typeof data !== 'object' || data === null || !('error' in data)) return undefined
  const error = data.error
  if (typeof error !== 'object' || error === null || !('message' in error)) return undefined
  return typeof error.message === 'string' ? error.message : undefined
}

export function normalizeApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (axios.isAxiosError<unknown>(error)) {
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return new ApiError('请求超时，请稍后重试', 'timeout')
    }
    if (error.response) {
      return new ApiError(
        serverMessage(error.response.data) || '请求失败，请稍后重试',
        'http',
        error.response.status,
      )
    }
    return new ApiError('无法连接服务，请检查网络或服务状态', 'network')
  }
  return new ApiError('请求失败，请稍后重试', 'unknown')
}

export function createApiClient(
  baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1',
): AxiosInstance {
  const client = axios.create({ baseURL, timeout: 10_000 })
  client.interceptors.request.use(
    (config) => {
      config.headers.set(
        'Accept',
        config.responseType === 'stream' ? 'text/event-stream' : 'application/json',
      )
      return config
    },
    (error: unknown) => Promise.reject(normalizeApiError(error)),
  )
  client.interceptors.response.use(
    (response) => response,
    async (error: unknown) => {
      if (
        axios.isAxiosError<unknown>(error) &&
        error.response &&
        error.config?.responseType === 'stream' &&
        error.response.data instanceof ReadableStream
      ) {
        const reader = error.response.data.getReader()
        const decoder = new TextDecoder()
        let body = ''
        try {
          while (body.length < 16384) {
            const { done, value } = await reader.read()
            if (done) break
            body += decoder.decode(value, { stream: true })
          }
          if (body.length < 16384) error.response.data = JSON.parse(body)
        } catch {
          /* 未知错误正文统一使用通用提示。 */
        } finally {
          await reader.cancel().catch(() => undefined)
          reader.releaseLock()
        }
      }
      return Promise.reject(normalizeApiError(error))
    },
  )
  return client
}

export const apiClient = createApiClient()
