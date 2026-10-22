import { ApiError, apiClient } from '../../api/client'
import { getEventStream } from '../../api/stream'
import { isRunView } from './types'
import type {
  AnalysisConfig,
  AnalysisOptions,
  DocumentDetail,
  DocumentKind,
  DocumentView,
  MCPServerInput,
  MCPServerView,
  MCPTool,
  RunInput,
  RunView,
  WorkspaceView,
} from './types'
const root = '/document-analysis'
const workspace = (id: string): string => `${root}/workspaces/${encodeURIComponent(id)}`
const doc = (id: string, documentId: string): string =>
  `${workspace(id)}/documents/${encodeURIComponent(documentId)}`
const run = (id: string, runId: string): string =>
  `${workspace(id)}/runs/${encodeURIComponent(runId)}`
export const analysisApi = {
  async options(): Promise<AnalysisOptions> {
    return (await apiClient.get<AnalysisOptions>(`${root}/options`)).data
  },
  async workspaces(): Promise<WorkspaceView[]> {
    return (await apiClient.get<WorkspaceView[]>(`${root}/workspaces`)).data
  },
  async saveWorkspace(name: string, id?: string): Promise<WorkspaceView> {
    return (
      id
        ? await apiClient.patch<WorkspaceView>(workspace(id), { name })
        : await apiClient.post<WorkspaceView>(`${root}/workspaces`, { name })
    ).data
  },
  async deleteWorkspace(id: string): Promise<void> {
    await apiClient.delete(workspace(id))
  },
  async documents(id: string): Promise<DocumentView[]> {
    return (await apiClient.get<DocumentView[]>(`${workspace(id)}/documents`)).data
  },
  async upload(id: string, file: File): Promise<DocumentView> {
    const data = new FormData()
    data.append('file', file)
    return (
      await apiClient.post<DocumentView>(`${workspace(id)}/documents`, data, { timeout: 120000 })
    ).data
  },
  async document(id: string, documentId: string): Promise<DocumentDetail> {
    return (await apiClient.get<DocumentDetail>(doc(id, documentId))).data
  },
  async changeKind(id: string, documentId: string, kind: DocumentKind): Promise<DocumentView> {
    return (await apiClient.patch<DocumentView>(doc(id, documentId), { kind })).data
  },
  async deleteDocument(id: string, documentId: string): Promise<void> {
    await apiClient.delete(doc(id, documentId))
  },
  async original(id: string, documentId: string): Promise<Blob> {
    return (
      await apiClient.get<Blob>(`${doc(id, documentId)}/original`, {
        responseType: 'blob',
        timeout: 60000,
      })
    ).data
  },
  async runs(id: string): Promise<RunView[]> {
    return (await apiClient.get<RunView[]>(`${workspace(id)}/runs`)).data
  },
  async createRun(id: string, input: RunInput): Promise<RunView> {
    return (await apiClient.post<RunView>(`${workspace(id)}/runs`, input)).data
  },
  async run(id: string, runId: string): Promise<RunView> {
    return (await apiClient.get<RunView>(run(id, runId))).data
  },
  async watchRun(
    id: string,
    runId: string,
    signal: AbortSignal,
    onSnapshot: (row: RunView) => void,
  ): Promise<void> {
    await getEventStream(`${run(id, runId)}/events`, signal, (event) => {
      if (event.kind === 'snapshot') {
        if (!isRunView(event.data) || event.data.id !== runId || event.data.workspace_id !== id)
          throw new ApiError('任务状态格式异常，请稍后重试', 'unknown')
        onSnapshot(event.data)
      } else if (event.kind === 'stream_error') {
        const unavailable =
          typeof event.data === 'object' &&
          event.data !== null &&
          'retryable' in event.data &&
          event.data.retryable === false
        throw new ApiError(
          unavailable ? '分析任务已不可用，请刷新页面' : '状态连接中断，正在重新连接',
          unavailable ? 'http' : 'network',
          unavailable ? 404 : undefined,
        )
      }
    })
  },
  async runAction(
    id: string,
    runId: string,
    action: 'cancel' | 'retry' | 'resume',
    answer?: string,
  ): Promise<RunView> {
    return (
      await apiClient.post<RunView>(
        `${run(id, runId)}/${action}`,
        action === 'resume' ? { answer } : undefined,
      )
    ).data
  },
  async export(id: string, runId: string): Promise<Blob> {
    return (
      await apiClient.get<Blob>(`${run(id, runId)}/export`, {
        responseType: 'blob',
        timeout: 60000,
      })
    ).data
  },
  async config(): Promise<AnalysisConfig> {
    return (await apiClient.get<AnalysisConfig>(`${root}/config`)).data
  },
  async saveConfig(input: AnalysisConfig): Promise<AnalysisConfig> {
    return (await apiClient.put<AnalysisConfig>(`${root}/config`, input)).data
  },
  async servers(): Promise<MCPServerView[]> {
    return (await apiClient.get<MCPServerView[]>(`${root}/mcp-servers`)).data
  },
  async saveServer(input: MCPServerInput, id?: string): Promise<MCPServerView> {
    return (
      id
        ? await apiClient.put<MCPServerView>(`${root}/mcp-servers/${encodeURIComponent(id)}`, input)
        : await apiClient.post<MCPServerView>(`${root}/mcp-servers`, input)
    ).data
  },
  async deleteServer(id: string): Promise<void> {
    await apiClient.delete(`${root}/mcp-servers/${encodeURIComponent(id)}`)
  },
  async discover(id: string): Promise<MCPTool[]> {
    return (
      await apiClient.post<MCPTool[]>(
        `${root}/mcp-servers/${encodeURIComponent(id)}/discover`,
        undefined,
        { timeout: 120000 },
      )
    ).data
  },
}
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
