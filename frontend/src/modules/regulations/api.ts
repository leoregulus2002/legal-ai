import { apiClient } from '../../api/client'
import type { RegulationDetail, RegulationOptions, RegulationPage } from './types'

const root = '/knowledge-bases/regulations'
export const regulationApi = {
  async options(): Promise<RegulationOptions> {
    return (await apiClient.get<RegulationOptions>(`${root}/options`)).data
  },
  async search(params: Record<string, string>): Promise<RegulationPage> {
    return (
      await apiClient.get<RegulationPage>(root, {
        params: Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '')),
        timeout: 30000,
      })
    ).data
  },
  async detail(id: string): Promise<RegulationDetail> {
    return (await apiClient.get<RegulationDetail>(`${root}/${encodeURIComponent(id)}`)).data
  },
}
