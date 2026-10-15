import { ApiError, apiClient } from './client'

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
