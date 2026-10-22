import { ApiError, apiClient } from './client'
import type { AxiosResponse } from 'axios'

export interface StreamEvent {
  kind: string
  data: unknown
}

export async function postEventStream(
  path: string,
  payload: unknown,
  signal: AbortSignal,
  timeout: number,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await apiClient.post<ReadableStream<Uint8Array>>(path, payload, {
    adapter: 'fetch',
    responseType: 'stream',
    signal,
    timeout,
  })
  await readEventStream(response, onEvent)
}

export async function getEventStream(
  path: string,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const controller = new AbortController()
  let idleTimer: ReturnType<typeof setTimeout> | undefined
  let timedOut = false
  const activity = (): void => {
    clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, 45_000)
  }
  activity()
  try {
    const response = await apiClient.get<ReadableStream<Uint8Array>>(path, {
      adapter: 'fetch',
      responseType: 'stream',
      signal: AbortSignal.any([signal, controller.signal]),
      timeout: 0,
    })
    await readEventStream(response, onEvent, activity)
  } catch (error: unknown) {
    if (timedOut && !signal.aborted) throw new ApiError('状态连接超时，正在重新连接', 'timeout')
    throw error
  } finally {
    clearTimeout(idleTimer)
    controller.abort()
  }
}

async function readEventStream(
  response: AxiosResponse<ReadableStream<Uint8Array>>,
  onEvent: (event: StreamEvent) => void,
  onActivity?: () => void,
): Promise<void> {
  if (
    !String(response.headers['content-type']).includes('text/event-stream') ||
    typeof response.data?.getReader !== 'function'
  ) {
    throw new ApiError('服务返回格式异常，请稍后重试', 'unknown')
  }
  const reader = response.data.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      onActivity?.()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      if (buffer.length > 1_000_000) throw new ApiError('流式响应过长，请重新发送', 'unknown')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const lines = frame.split('\n')
        const kind = lines
          .find((line) => line.startsWith('event:'))
          ?.slice(6)
          .trim()
        const data = lines
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n')
        if (kind && data) {
          let parsed: unknown
          try {
            parsed = JSON.parse(data)
          } catch {
            throw new ApiError('流式响应格式异常，请重新发送', 'unknown')
          }
          onEvent({ kind, data: parsed })
        }
      }
      if (done) break
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
