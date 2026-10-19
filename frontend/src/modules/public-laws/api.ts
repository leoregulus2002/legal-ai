import { apiClient } from '../../api/client'
import type {
  PublicLaw,
  PublicLawDetail,
  PublicLawFormat,
  PublicLawImportResult,
  PublicLawImportState,
  PublicLawOptions,
  PublicLawPage,
  PublicLawQuery,
  VectorTask,
} from './types'

export const publicLawApi = {
  async latestTask(): Promise<VectorTask | null> {
    return (await apiClient.get<VectorTask | null>('/public-laws/vector-tasks/latest')).data
  },
  async startTask(
    knowledgeBaseId: string,
    embeddingModelId: string,
    scope: { query: PublicLawQuery } | { laws: PublicLaw[] },
  ): Promise<VectorTask> {
    return (
      await apiClient.post<VectorTask>('/public-laws/vector-tasks', {
        knowledge_base_id: knowledgeBaseId,
        embedding_model_id: embeddingModelId,
        ...('query' in scope
          ? { query: scope.query }
          : {
              laws: scope.laws.map((law) => ({
                id: law.id,
                title: law.title,
                decision: law.category === '修改、废止的决定',
              })),
            }),
      })
    ).data
  },
  async stopTask(id: string): Promise<VectorTask> {
    return (await apiClient.post<VectorTask>(`/public-laws/vector-tasks/${id}/stop`)).data
  },
  async importLaw(
    law: PublicLaw,
    knowledgeBaseId: string,
    embeddingModelId: string,
  ): Promise<PublicLawImportResult> {
    return (
      await apiClient.post<PublicLawImportResult>(
        `/public-laws/${encodeURIComponent(law.id)}/import`,
        {
          knowledge_base_id: knowledgeBaseId,
          embedding_model_id: embeddingModelId,
          decision: law.category === '修改、废止的决定',
        },
        { timeout: 120_000 },
      )
    ).data
  },
  async importStatus(ids: string[]): Promise<PublicLawImportState[]> {
    return (await apiClient.post<PublicLawImportState[]>('/public-laws/import-status', { ids }))
      .data
  },
  async detail(law: PublicLaw, signal: AbortSignal): Promise<PublicLawDetail> {
    return (
      await apiClient.get<PublicLawDetail>(`/public-laws/${encodeURIComponent(law.id)}`, {
        params: { decision: law.category === '修改、废止的决定' },
        signal,
        timeout: 35_000,
      })
    ).data
  },
  async preview(
    law: PublicLaw,
    format: PublicLawFormat,
    signal: AbortSignal,
  ): Promise<{ url: string }> {
    return (
      await apiClient.get<{ url: string }>(`/public-laws/${encodeURIComponent(law.id)}/preview`, {
        params: { format, decision: law.category === '修改、废止的决定' },
        signal,
        timeout: 70_000,
      })
    ).data
  },
  async download(law: PublicLaw, format: PublicLawFormat, signal: AbortSignal): Promise<Blob> {
    return (
      await apiClient.get<Blob>(`/public-laws/${encodeURIComponent(law.id)}/download`, {
        params: { format },
        signal,
        responseType: 'blob',
        timeout: 90_000,
      })
    ).data
  },
  async options(): Promise<PublicLawOptions> {
    return (await apiClient.get<PublicLawOptions>('/public-laws/options', { timeout: 35_000 })).data
  },
  async search(query: PublicLawQuery): Promise<PublicLawPage> {
    return (await apiClient.post<PublicLawPage>('/public-laws/search', query, { timeout: 180_000 }))
      .data
  },
  async downloads(ids: string[]): Promise<{ url: string }[]> {
    return (
      await apiClient.post<{ url: string }[]>(
        '/public-laws/downloads',
        { ids },
        { timeout: 35_000 },
      )
    ).data
  },
}
