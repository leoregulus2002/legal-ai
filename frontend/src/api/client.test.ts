import { AxiosError, AxiosHeaders } from 'axios'
import type { AxiosAdapter, AxiosResponse } from 'axios'
import { describe, expect, it } from 'vitest'
import { ApiError, createApiClient } from './client'

const response =
  (status: number, data: unknown): AxiosAdapter =>
  async (config) => {
    const result: AxiosResponse<unknown> = {
      data,
      status,
      statusText: '',
      headers: new AxiosHeaders(),
      config,
    }
    if (status >= 400) throw new AxiosError('failed', 'ERR_BAD_RESPONSE', config, undefined, result)
    return result
  }

describe('API client', () => {
  it('uses the API prefix, timeout, and request interceptor', async () => {
    const client = createApiClient('/api/v1')
    client.defaults.adapter = async (config) => {
      expect(config.baseURL).toBe('/api/v1')
      expect(config.timeout).toBe(10_000)
      expect(config.headers.get('Accept')).toBe('application/json')
      return response(200, { status: 'ok' })(config)
    }
    expect((await client.get('/health')).data).toEqual({ status: 'ok' })
  })
  it('normalizes HTTP errors with backend messages', async () => {
    const client = createApiClient()
    client.defaults.adapter = response(503, { error: { message: '服务暂不可用' } })
    await expect(client.get('/health')).rejects.toMatchObject({
      kind: 'http',
      status: 503,
      message: '服务暂不可用',
    })
  })
  it.each([
    ['ECONNABORTED', 'timeout'],
    ['ERR_NETWORK', 'network'],
  ])('normalizes %s', async (code, kind) => {
    const client = createApiClient()
    client.defaults.adapter = async () => {
      throw new AxiosError('failure', code)
    }
    await expect(client.get('/health')).rejects.toBeInstanceOf(ApiError)
    await expect(client.get('/health')).rejects.toMatchObject({ kind })
  })
})
