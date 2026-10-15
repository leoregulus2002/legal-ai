import { apiClient } from '../../api/client'
import type { Attachment, ConsultationOptions, Conversation, Turn } from './types'

export const consultationApi = {
  async options(): Promise<ConsultationOptions> {
    return (await apiClient.get<ConsultationOptions>('/consultation/options')).data
  },
  async conversations(offset = 0): Promise<Conversation[]> {
    return (
      await apiClient.get<Conversation[]>('/consultation/conversations', {
        params: { offset, limit: 50 },
      })
    ).data
  },
  async create(): Promise<Conversation> {
    return (await apiClient.post<Conversation>('/consultation/conversations', { title: '新对话' }))
      .data
  },
  async delete(id: string): Promise<void> {
    await apiClient.delete(`/consultation/conversations/${id}`)
  },
  async turns(id: string, after = 0): Promise<Turn[]> {
    return (
      await apiClient.get<Turn[]>(`/consultation/conversations/${id}/messages`, {
        params: { after, limit: 100 },
      })
    ).data
  },
  async attachments(id: string): Promise<Attachment[]> {
    return (await apiClient.get<Attachment[]>(`/consultation/conversations/${id}/attachments`)).data
  },
  async upload(id: string, file: File): Promise<Attachment> {
    const data = new FormData()
    data.append('file', file)
    return (
      await apiClient.post<Attachment>(`/consultation/conversations/${id}/attachments`, data, {
        timeout: 60000,
      })
    ).data
  },
  async removeAttachment(id: string): Promise<void> {
    await apiClient.delete(`/consultation/attachments/${id}`)
  },
  async downloadAttachment(id: string): Promise<Blob> {
    return (
      await apiClient.get<Blob>(`/consultation/attachments/${id}`, {
        responseType: 'blob',
        timeout: 60000,
      })
    ).data
  },
}
