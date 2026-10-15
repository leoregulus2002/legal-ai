import { apiClient } from '../../api/client'
import type {
  ModelConfig,
  ModelInput,
  PolicyInput,
  PolicyView,
  PromptInput,
  PromptVersion,
  SystemPrompt,
} from './types'

export const configApi = {
  async models(): Promise<ModelConfig[]> {
    return (await apiClient.get<ModelConfig[]>('/system-config/models')).data
  },
  async saveModel(data: ModelInput, id?: string): Promise<ModelConfig> {
    return (
      id
        ? await apiClient.put<ModelConfig>(`/system-config/models/${id}`, data)
        : await apiClient.post<ModelConfig>('/system-config/models', data)
    ).data
  },
  async prompts(): Promise<SystemPrompt[]> {
    return (await apiClient.get<SystemPrompt[]>('/system-config/prompts')).data
  },
  async savePrompt(data: PromptInput, id?: string): Promise<SystemPrompt> {
    return (
      id
        ? await apiClient.put<SystemPrompt>(`/system-config/prompts/${id}`, data)
        : await apiClient.post<SystemPrompt>('/system-config/prompts', data)
    ).data
  },
  async versions(id: string): Promise<PromptVersion[]> {
    return (await apiClient.get<PromptVersion[]>(`/system-config/prompts/${id}/versions`)).data
  },
  async deletePrompt(id: string): Promise<void> {
    await apiClient.delete(`/system-config/prompts/${id}`)
  },
  async policy(): Promise<PolicyView> {
    return (await apiClient.get<PolicyView>('/system-config/consultation')).data
  },
  async savePolicy(data: PolicyInput): Promise<PolicyView> {
    return (await apiClient.put<PolicyView>('/system-config/consultation', data)).data
  },
}
