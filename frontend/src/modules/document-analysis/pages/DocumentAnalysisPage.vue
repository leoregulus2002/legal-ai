<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NSpin,
  NTag,
  useDialog,
  useMessage,
} from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { ApiError, normalizeApiError } from '../../../api/client'
import { analysisApi, downloadBlob } from '../api'
import AnalysisTurn from '../components/AnalysisTurn.vue'
import OriginalDocument from '../components/OriginalDocument.vue'
import { isActive } from '../types'
import type {
  DocumentCitation,
  DocumentDetail,
  DocumentView,
  RunInput,
  RunView,
  WorkspaceView,
} from '../types'
import { useAnalysisError } from '../useAnalysisError'
import '../styles.css'

const route = useRoute()
const router = useRouter()
const dialog = useDialog()
const message = useMessage()
const showError = useAnalysisError()
const workspaces = ref<WorkspaceView[]>([])
const workspaceId = ref<string | null>(
  typeof route.query.workspace === 'string' ? route.query.workspace : null,
)
const documents = ref<DocumentView[]>([])
const runs = ref<RunView[]>([])
const input = ref('')
const loading = ref(false)
const submitting = ref(false)
const uploading = ref(false)
const actionId = ref<string | null>(null)
const sourcesOpen = ref(false)
const detail = ref<DocumentDetail | null>(null)
const documentId = ref<string | null>(null)
const documentLoading = ref(false)
const downloading = ref(false)
const highlight = ref<string | null>(null)
const fileInput = ref<HTMLInputElement>()
const messageArea = ref<HTMLElement>()
let alive = true
let workspaceGeneration = 0
let detailGeneration = 0
let streamController: AbortController | undefined
let reconnectTimer: ReturnType<typeof setTimeout> | undefined
let streamRunId: string | undefined
let streamErrorShown = false
let reconnectAttempts = 0
let newWorkspacePromise: Promise<string> | undefined
let pendingSend: { workspaceId: string; data: RunInput } | undefined
const notifiedFailures = new Set<string>()
const messages = computed(() =>
  [...runs.value].sort((a, b) => a.created_at.localeCompare(b.created_at)),
)
const pendingDocuments = computed(() => {
  const sentDocumentIds = new Set(runs.value.flatMap((row) => row.document_ids))
  return documents.value.filter((doc) => !sentDocumentIds.has(doc.id))
})
const latest = computed(() => messages.value.at(-1))
const running = computed(() => runs.value.find((row) => isActive(row.status)))
const pendingQuestion = computed(() =>
  latest.value?.status === 'needs_input' ? latest.value : undefined,
)
const busy = computed(() => submitting.value || uploading.value || loading.value)
const placeholder = computed(() =>
  pendingQuestion.value
    ? '补充你的情况，AI 会接着分析…'
    : '告诉我你想了解什么，例如：我是乙方，帮我看看合同里的付款和违约风险…',
)

function syncQuery(): void {
  void router
    .replace({
      query: { ...route.query, workspace: workspaceId.value || undefined, run: undefined },
    })
    .catch(() => undefined)
}
function stopStream(): void {
  streamController?.abort()
  streamController = undefined
  clearTimeout(reconnectTimer)
  reconnectTimer = undefined
  streamRunId = undefined
  streamErrorShown = false
  reconnectAttempts = 0
}
function upsert(row: RunView): void {
  const workspace = workspaces.value.find((item) => item.id === row.workspace_id)
  if (workspace && row.workspace_name?.trim()) workspace.name = row.workspace_name
  const previous = runs.value.find((item) => item.id === row.id)
  runs.value = [row, ...runs.value.filter((item) => item.id !== row.id)]
  if (row.status === 'failed' && previous && isActive(previous.status)) {
    const key = `${row.id}:${row.updated_at}`
    if (!notifiedFailures.has(key)) {
      notifiedFailures.add(key)
      message.error(row.failure_message?.trim().slice(0, 300) || '分析未完成，请稍后重试')
    }
  }
  if (!previous || previous.status !== row.status) void scrollToBottom()
}
async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (alive && messageArea.value) messageArea.value.scrollTop = messageArea.value.scrollHeight
}
function subscribeRun(id: string, generation: number): void {
  const active = running.value
  if (!alive || id !== workspaceId.value || generation !== workspaceGeneration) return
  if (active?.id === streamRunId) return
  stopStream()
  if (!active) return
  streamRunId = active.id
  const controller = new AbortController()
  streamController = controller
  let lastSnapshot = ''
  const current = (): boolean =>
    alive &&
    !controller.signal.aborted &&
    streamController === controller &&
    id === workspaceId.value &&
    generation === workspaceGeneration
  const connect = async (): Promise<void> => {
    if (!current()) return
    try {
      await analysisApi.watchRun(id, active.id, controller.signal, (row) => {
        if (!current()) return
        upsert(row)
        const snapshot = JSON.stringify(row)
        // 仅快照变化才重置退避和提示，避免反复收到同一快照后断连。
        if (snapshot !== lastSnapshot) {
          lastSnapshot = snapshot
          streamErrorShown = false
          reconnectAttempts = 0
        }
        if (!isActive(row.status)) stopStream()
      })
      if (!current()) return
      throw new ApiError('状态连接中断，正在重新连接', 'network')
    } catch (error: unknown) {
      if (!current()) return
      const normalized = normalizeApiError(error)
      if (!streamErrorShown) {
        showError(normalized)
        streamErrorShown = true
      }
      if (
        normalized.kind === 'http' &&
        normalized.status !== undefined &&
        normalized.status >= 400 &&
        normalized.status < 500 &&
        ![408, 429].includes(normalized.status)
      ) {
        stopStream()
        return
      }
      const delay = Math.min(1000 * 2 ** Math.min(reconnectAttempts++, 5), 30_000)
      reconnectTimer = setTimeout(() => {
        reconnectTimer = undefined
        void connect()
      }, delay)
    }
  }
  void connect()
}
async function selectWorkspace(id: string | null): Promise<void> {
  const generation = ++workspaceGeneration
  pendingSend = undefined
  ++detailGeneration
  stopStream()
  workspaceId.value = id
  runs.value = []
  documents.value = []
  detail.value = null
  documentId.value = null
  highlight.value = null
  documentLoading.value = false
  input.value = ''
  syncQuery()
  if (!id) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const [docs, history] = await Promise.all([analysisApi.documents(id), analysisApi.runs(id)])
    if (!alive || generation !== workspaceGeneration) return
    documents.value = docs
    runs.value = history
    const active = history.find((row) => isActive(row.status)) ?? history[0]
    if (active) {
      const row = await analysisApi.run(id, active.id)
      if (!alive || generation !== workspaceGeneration) return
      upsert(row)
    }
    if (!alive || generation !== workspaceGeneration) return
    subscribeRun(id, generation)
    void scrollToBottom()
  } catch (error: unknown) {
    if (alive && generation === workspaceGeneration) showError(error)
  } finally {
    if (alive && generation === workspaceGeneration) loading.value = false
  }
}
async function initialize(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    const rows = await analysisApi.workspaces()
    if (!alive) return
    workspaces.value = rows
    const id = rows.some((row) => row.id === workspaceId.value) ? workspaceId.value : null
    loading.value = false
    await selectWorkspace(id)
  } catch (error: unknown) {
    if (alive) {
      showError(error)
      loading.value = false
    }
  }
}
async function ensureWorkspace(): Promise<string> {
  if (workspaceId.value) return workspaceId.value
  if (newWorkspacePromise) return newWorkspacePromise
  const generation = workspaceGeneration
  newWorkspacePromise = (async () => {
    const row = await analysisApi.saveWorkspace('新文书对话')
    if (!alive) return row.id
    workspaces.value = [row, ...workspaces.value]
    if (generation !== workspaceGeneration) return row.id
    workspaceId.value = row.id
    syncQuery()
    return row.id
  })()
  try {
    return await newWorkspacePromise
  } finally {
    newWorkspacePromise = undefined
  }
}
async function send(): Promise<void> {
  const instruction = input.value.trim()
  if (!instruction || busy.value || running.value || actionId.value) return
  submitting.value = true
  try {
    const id = await ensureWorkspace()
    if (!alive || id !== workspaceId.value) return
    const generation = workspaceGeneration
    const question = pendingQuestion.value
    const parent = [...messages.value]
      .reverse()
      .find((row) => row.status === 'completed' || row.status === 'partial')
    if (
      !question &&
      (!pendingSend ||
        pendingSend.workspaceId !== id ||
        pendingSend.data.instruction !== instruction ||
        pendingSend.data.parent_run_id !== (parent?.id ?? null))
    ) {
      pendingSend = {
        workspaceId: id,
        data: {
          request_id: crypto.randomUUID(),
          instruction,
          parent_run_id: parent?.id ?? null,
        },
      }
    }
    const row = question
      ? await analysisApi.runAction(id, question.id, 'resume', instruction)
      : await analysisApi.createRun(id, pendingSend!.data)
    if (!alive || id !== workspaceId.value || generation !== workspaceGeneration) return
    if (input.value.trim() === instruction) input.value = ''
    pendingSend = undefined
    upsert(row)
    subscribeRun(id, generation)
    void scrollToBottom()
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) submitting.value = false
  }
}
async function upload(event: Event): Promise<void> {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  const files = Array.from(target.files ?? [])
  target.value = ''
  if (!files.length || busy.value || running.value) return
  if (files.some((file) => file.size > 20 * 1024 * 1024)) {
    message.warning('单份文书不能超过 20 MB')
    return
  }
  uploading.value = true
  try {
    const id = await ensureWorkspace()
    const generation = workspaceGeneration
    for (const file of files) {
      if (!alive || id !== workspaceId.value || generation !== workspaceGeneration) return
      const doc = await analysisApi.upload(id, file)
      if (!alive || id !== workspaceId.value || generation !== workspaceGeneration) return
      documents.value = [...documents.value, doc]
      if (doc.status === 'needs_ocr') message.warning('部分文字未能提取，请完成 OCR 后重新上传')
    }
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) uploading.value = false
  }
}
async function runAction(row: RunView, action: 'cancel' | 'retry'): Promise<void> {
  const id = workspaceId.value
  if (!id || busy.value || actionId.value || (action === 'retry' && running.value)) return
  actionId.value = row.id
  const generation = workspaceGeneration
  try {
    const updated = await analysisApi.runAction(id, row.id, action)
    if (!alive || generation !== workspaceGeneration) return
    upsert(updated)
    subscribeRun(id, generation)
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) actionId.value = null
  }
}
async function loadDocument(id: string): Promise<void> {
  const workspace = workspaceId.value
  if (!workspace) return
  const generation = ++detailGeneration
  documentId.value = id
  detail.value = null
  highlight.value = null
  documentLoading.value = true
  try {
    const row = await analysisApi.document(workspace, id)
    if (alive && generation === detailGeneration && workspace === workspaceId.value)
      detail.value = row
  } catch (error: unknown) {
    if (alive && generation === detailGeneration) showError(error)
  } finally {
    if (alive && generation === detailGeneration) documentLoading.value = false
  }
}
function openDocument(id: string): void {
  sourcesOpen.value = true
  void loadDocument(id)
}
async function locate(citation: DocumentCitation): Promise<void> {
  sourcesOpen.value = true
  const workspace = workspaceId.value
  await loadDocument(citation.document_id)
  if (!alive || workspace !== workspaceId.value || detail.value?.id !== citation.document_id) return
  if (detail.value.revision !== citation.revision) {
    message.warning('引用版本与当前原文不同，请核对原件')
    return
  }
  if (!detail.value.spans.some((span) => span.id === citation.span_id)) {
    message.warning('未找到对应的原文位置')
    return
  }
  highlight.value = citation.span_id
}
async function downloadOriginal(): Promise<void> {
  const id = workspaceId.value
  const doc = detail.value
  if (!id || !doc || downloading.value) return
  downloading.value = true
  try {
    downloadBlob(await analysisApi.original(id, doc.id), doc.filename)
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) downloading.value = false
  }
}
async function exportReport(row: RunView): Promise<void> {
  if (!workspaceId.value) return
  try {
    downloadBlob(await analysisApi.export(workspaceId.value, row.id), '法律文书分析报告.md')
  } catch (error: unknown) {
    if (alive) showError(error)
  }
}
function deleteWorkspace(row: WorkspaceView): void {
  if (busy.value || actionId.value || (workspaceId.value === row.id && running.value)) return
  dialog.warning({
    title: '删除对话',
    content: `确认删除“${row.name}”及其文书和分析记录？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await analysisApi.deleteWorkspace(row.id)
        if (!alive) return
        workspaces.value = workspaces.value.filter((item) => item.id !== row.id)
        if (workspaceId.value === row.id) await selectWorkspace(null)
      } catch (error: unknown) {
        if (alive) showError(error)
        return false
      }
    },
  })
}
function removeDocument(doc: DocumentView): void {
  const id = workspaceId.value
  if (!id || busy.value || running.value) return
  dialog.warning({
    title: '移除文书',
    content: '移除后不再参与后续分析，已有报告的原文引用会保留。',
    positiveText: '移除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await analysisApi.deleteDocument(id, doc.id)
        if (alive && id === workspaceId.value)
          documents.value = documents.value.filter((item) => item.id !== doc.id)
      } catch (error: unknown) {
        if (alive) showError(error)
        return false
      }
    },
  })
}
function keydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}
watch(
  () => route.query.workspace,
  (value) => {
    const id = typeof value === 'string' ? value : null
    if (id !== workspaceId.value) void selectWorkspace(id)
  },
)
onMounted(() => {
  void initialize()
})
onBeforeUnmount(() => {
  alive = false
  stopStream()
  ++workspaceGeneration
  ++detailGeneration
})
</script>

<template>
  <section class="document-analysis-page analysis-chat-page">
    <aside class="analysis-chat-sidebar">
      <NButton block :disabled="busy || !!actionId" @click="selectWorkspace(null)"
        ><template #icon><AppIcon name="plus" :size="17" /></template>新建文书对话</NButton
      >
      <p class="analysis-chat-sidebar-label">最近对话</p>
      <nav class="analysis-chat-conversations" aria-label="文书分析对话">
        <div
          v-for="workspace in workspaces"
          :key="workspace.id"
          class="analysis-chat-conversation"
          :class="{ 'is-active': workspace.id === workspaceId }"
        >
          <button :disabled="busy" :title="workspace.name" @click="selectWorkspace(workspace.id)">
            <AppIcon name="chat" :size="16" /><span>{{ workspace.name }}</span>
          </button>
          <button
            class="analysis-chat-delete"
            :disabled="busy || (workspace.id === workspaceId && !!running)"
            aria-label="删除对话"
            @click="deleteWorkspace(workspace)"
          >
            <AppIcon name="close" :size="13" />
          </button>
        </div>
        <p v-if="!workspaces.length" class="analysis-muted">
          上传文书或发送需求后，会自动保存对话。
        </p>
      </nav>
      <RouterLink class="analysis-chat-settings" to="/settings/document-analysis"
        ><AppIcon name="settings" :size="16" />文书分析配置</RouterLink
      >
    </aside>
    <div class="analysis-chat-main">
      <header class="analysis-chat-header">
        <div>
          <h1>法律文书分析</h1>
          <span>AI 自动理解需求、识别立场并按需调用工具</span>
        </div>
        <NButton quaternary size="small" @click="sourcesOpen = true"
          ><template #icon><AppIcon name="document" :size="17" /></template>文书
          {{ documents.length || '' }}</NButton
        >
      </header>
      <div ref="messageArea" class="analysis-chat-messages" :aria-busy="!!running || loading">
        <NSpin :show="loading"
          ><div v-if="!messages.length && !loading" class="analysis-chat-welcome">
            <div class="analysis-chat-welcome-icon"><AppIcon name="column" :size="36" /></div>
            <h2>把文书交给我，告诉我你的需求</h2>
            <p>
              上传合同、诉讼材料或裁判文书，直接开始对话。<br />我会判断分析方向、梳理事实，并按需查找依据。
            </p>
            <div class="analysis-chat-suggestions">
              <button @click="input = '我是乙方，帮我审查合同中的付款和违约风险。'">
                审查合同风险<AppIcon name="arrow-right" :size="16" /></button
              ><button @click="input = '帮我梳理诉讼请求、事实和证据之间的对应关系。'">
                梳理事实与证据<AppIcon name="arrow-right" :size="16" /></button
              ><button @click="input = '解释这份裁判文书的争议焦点和裁判理由。'">
                解读裁判文书<AppIcon name="arrow-right" :size="16" />
              </button>
            </div>
          </div>
          <div v-else class="analysis-chat-thread">
            <AnalysisTurn
              v-for="row in messages"
              :key="row.id"
              :run="row"
              :documents="documents"
              :latest="row.id === latest?.id"
              :action-busy="actionId === row.id"
              @cite="locate"
              @cancel="runAction(row, 'cancel')"
              @retry="runAction(row, 'retry')"
              @export="exportReport(row)"
            />
          </div>
        </NSpin>
      </div>
      <footer class="analysis-chat-composer-wrap">
        <div class="analysis-chat-composer">
          <div v-if="pendingDocuments.length" class="analysis-chat-attachments">
            <button v-for="doc in pendingDocuments" :key="doc.id" @click="openDocument(doc.id)">
              <AppIcon name="document" :size="15" /><span>{{ doc.filename }}</span
              ><NTag v-if="doc.status === 'needs_ocr'" size="tiny" type="warning">需 OCR</NTag>
            </button>
          </div>
          <NInput
            v-model:value="input"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 7 }"
            :maxlength="10000"
            :placeholder="placeholder"
            :disabled="loading"
            @keydown="keydown"
          />
          <div class="analysis-chat-composer-actions">
            <NButton
              quaternary
              size="small"
              :loading="uploading"
              :disabled="busy || !!running"
              @click="fileInput?.click()"
              ><template #icon><AppIcon name="plus" :size="18" /></template>上传文书</NButton
            ><span>{{
              pendingQuestion ? '直接回答上面的问题即可' : '意图、立场与工具由 AI 自动判断'
            }}</span
            ><NButton
              v-if="running"
              secondary
              :loading="actionId === running.id"
              @click="runAction(running, 'cancel')"
              >停止</NButton
            ><NButton
              v-else
              type="primary"
              circle
              :loading="submitting"
              :disabled="!input.trim() || busy || !!actionId"
              aria-label="发送"
              @click="send"
              ><template #icon><AppIcon name="arrow-up" :size="20" /></template
            ></NButton>
          </div>
        </div>
        <p class="analysis-chat-input-hint">
          Enter 发送 · Shift + Enter 换行 · 重要结论请结合原文核对
        </p>
      </footer>
      <input
        ref="fileInput"
        class="analysis-file-input"
        type="file"
        multiple
        accept=".pdf,.docx,.doc,.txt,.md,.markdown,.html,.htm"
        aria-label="上传法律文书"
        @change="upload"
      />
    </div>
    <NDrawer v-model:show="sourcesOpen" placement="right" :width="'min(640px, 100vw)'"
      ><NDrawerContent title="文书与原文" closable
        ><div class="analysis-chat-materials">
          <div v-for="doc in documents" :key="doc.id" class="analysis-chat-material">
            <button @click="loadDocument(doc.id)">
              <AppIcon name="document" :size="16" /><span>{{ doc.filename }}</span></button
            ><NButton text size="tiny" :disabled="busy || !!running" @click="removeDocument(doc)"
              >移除</NButton
            >
          </div>
          <NEmpty
            v-if="!documents.length && !detail"
            description="上传文书后，AI 会自动阅读并选择相关材料"
          />
        </div>
        <OriginalDocument
          :documents="documents"
          :selected="documentId"
          :detail="detail"
          :loading="documentLoading"
          :downloading="downloading"
          :highlight="highlight"
          @select="loadDocument"
          @download="downloadOriginal" /></NDrawerContent
    ></NDrawer>
  </section>
</template>
