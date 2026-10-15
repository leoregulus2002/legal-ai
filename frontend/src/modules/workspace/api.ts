import { ApiError, apiClient } from '../../api/client'

interface HealthResponse {
  status: 'ok'
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<unknown>('/health')
  const data = response.data
  if (typeof data !== 'object' || data === null || !('status' in data) || data.status !== 'ok') {
    throw new ApiError('暂时无法获取服务状态，请稍后重试', 'unknown')
  }
  return { status: 'ok' }
}
