import { apiClient } from '../../api/client'
import type {
  AuditEntry,
  Comparison,
  CorrectionInput,
  DocumentDetail,
  KnowledgeBase,
  KnowledgeDocument,
  Page,
  SearchPage,
  Segment,
  VersionCandidate,
} from './types'
const root = '/knowledge-bases'
const doc = (base: string, id: string): string => `${root}/${base}/documents/${id}`
export const knowledgeApi = {
  async bases(q = '', page = 1, pageSize = 12): Promise<Page<KnowledgeBase>> {
    return (
      await apiClient.get<Page<KnowledgeBase>>(root, { params: { q, page, page_size: pageSize } })
    ).data
  },
  async base(id: string): Promise<KnowledgeBase> {
    return (await apiClient.get<KnowledgeBase>(`${root}/${id}`)).data
  },
  async saveBase(data: { name: string; description: string }, id?: string): Promise<KnowledgeBase> {
    return (
      id
        ? await apiClient.put<KnowledgeBase>(`${root}/${id}`, data)
        : await apiClient.post<KnowledgeBase>(root, data)
    ).data
  },
  async deleteBase(id: string): Promise<void> {
    await apiClient.delete(`${root}/${id}`)
  },
  async documents(base: string, q = '', page = 1, status = ''): Promise<Page<KnowledgeDocument>> {
    return (
      await apiClient.get<Page<KnowledgeDocument>>(`${root}/${base}/documents`, {
        params: { q, page, page_size: 12, status: status || undefined },
      })
    ).data
  },
  async upload(
    base: string,
    data: FormData,
    onProgress: (percent: number) => void,
  ): Promise<KnowledgeDocument> {
    return (
      await apiClient.post<KnowledgeDocument>(`${root}/${base}/documents`, data, {
        timeout: 120000,
        onUploadProgress: (event) => {
          if (event.total) onProgress(Math.round((event.loaded / event.total) * 100))
        },
      })
    ).data
  },
  async detail(base: string, id: string, revision?: number): Promise<DocumentDetail> {
    return (await apiClient.get<DocumentDetail>(doc(base, id), { params: { revision } })).data
  },
  async status(base: string, id: string): Promise<KnowledgeDocument> {
    return (await apiClient.get<KnowledgeDocument>(`${doc(base, id)}/status`)).data
  },
  async remove(base: string, id: string): Promise<void> {
    await apiClient.delete(doc(base, id))
  },
  async original(base: string, id: string): Promise<Blob> {
    return (
      await apiClient.get<Blob>(`${doc(base, id)}/original`, {
        responseType: 'blob',
        timeout: 60000,
      })
    ).data
  },
  async correct(base: string, id: string, data: CorrectionInput): Promise<DocumentDetail> {
    return (
      await apiClient.put<DocumentDetail>(`${doc(base, id)}/correction`, data, { timeout: 60000 })
    ).data
  },
  async action(
    base: string,
    id: string,
    action: 'publish' | 'withdraw' | 'reparse',
    expected_revision: number,
    reason: string,
  ): Promise<KnowledgeDocument> {
    return (
      await apiClient.post<KnowledgeDocument>(`${doc(base, id)}/${action}`, {
        expected_revision,
        reason,
      })
    ).data
  },
  async vectorize(
    base: string,
    id: string,
    expected_revision: number,
    model_id: string,
  ): Promise<KnowledgeDocument> {
    return (
      await apiClient.post<KnowledgeDocument>(`${doc(base, id)}/vectorize`, {
        expected_revision,
        model_id,
        reason: '人工发起或重试向量化',
      })
    ).data
  },
  async segments(base: string, id: string, page = 1): Promise<Page<Segment>> {
    return (
      await apiClient.get<Page<Segment>>(`${doc(base, id)}/segments`, {
        params: { page, page_size: 10 },
      })
    ).data
  },
  async versions(base: string, id: string): Promise<VersionCandidate[]> {
    return (await apiClient.get<VersionCandidate[]>(`${doc(base, id)}/versions`)).data
  },
  async compare(base: string, id: string, other: string): Promise<Comparison> {
    return (
      await apiClient.get<Comparison>(`${doc(base, id)}/compare/${other}`, { timeout: 60000 })
    ).data
  },
  async audit(base: string, id?: string, page = 1): Promise<AuditEntry[]> {
    return (
      await apiClient.get<AuditEntry[]>(`${root}/${base}/audit`, {
        params: { document_id: id, page, page_size: 20 },
      })
    ).data
  },
  async search(q: string, base?: string, page = 1, model?: string): Promise<SearchPage> {
    return (
      await apiClient.get<SearchPage>(`${root}/search`, {
        timeout: 120000,
        params: { q, knowledge_base_id: base, page, page_size: 10, model_id: model },
      })
    ).data
  },
}
