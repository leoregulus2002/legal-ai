<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NDropdown, NEmpty, NInput, NPopconfirm, NSpin, useMessage } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { consultationApi } from '../api'
import ContextUsageIndicator from '../components/ContextUsageIndicator.vue'
import MessageAttachment from '../components/MessageAttachment.vue'
import MessageCopyButton from '../components/MessageCopyButton.vue'
import ReasoningPanel from '../components/ReasoningPanel.vue'
import { useConsultationStore } from '../store'
import type { Attachment, Source, Turn } from '../types'

const store = useConsultationStore()
const message = useMessage()
const showError = useErrorMessage()
const text = ref('')
const pending = ref<(Attachment & { preview?: string | undefined })[]>([])
const uploading = ref(false)
const picking = ref(false)
const submitting = ref(false)
let disposed = false
const input = ref<HTMLInputElement>()
const messageArea = ref<HTMLElement>()
const modelOptions = computed(
  () => store.options?.models.map((m) => ({ label: m.name, key: m.id })) ?? [],
)
const configured = computed(() => modelOptions.value.length > 0)
const chatTurns = computed(() =>
  [
    ...store.turns.map((turn) => ({
      key: `saved-${turn.id}`,
      user_text: turn.user_text,
      answer: turn.answer,
      reasoning: turn.reasoning ?? '',
      files: turnAttachments(turn),
      sources: turn.sources,
      modelLabel: modelName(turn),
      retrieval: retrievalLabel(turn),
      stopped: false,
      order: turn.sequence,
    })),
    ...store.stoppedTurns
      .filter((turn) => turn.conversation_id === store.activeId)
      .map((turn) => ({
        key: `stopped-${turn.request_id}`,
        user_text: turn.user_text,
        answer: turn.answer,
        reasoning: turn.reasoning,
        files: turn.attachments,
        sources: turn.sources,
        modelLabel: turn.model_name,
        retrieval: undefined,
        stopped: true,
        order: turn.after_sequence + 0.5,
      })),
  ].sort((left, right) => left.order - right.order),
)
const inputTheme = {
  color: 'transparent',
  colorHover: 'transparent',
  colorFocus: 'transparent',
  colorDisabled: 'transparent',
  boxShadowFocus: 'none',
}
const busy = computed(
  () => store.generating || submitting.value || uploading.value || picking.value || store.loading,
)
const accept = computed(() =>
  [
    store.model?.supports_images ? 'image/png,image/jpeg,image/webp' : '',
    store.model?.supports_pdf ? 'application/pdf' : '',
  ]
    .filter(Boolean)
    .join(','),
)

function selectModel(key: string | number): void {
  if (!busy.value) store.selectedModel = String(key)
}
function toggleKnowledge(): void {
  if (busy.value) return
  if (!store.knowledgeEnabled && !store.options?.policy.knowledge_base_ids?.length) {
    message.warning('请先在法律咨询模型中添加内部知识库')
    return
  }
  store.knowledgeEnabled = !store.knowledgeEnabled
}

function releasePreviews(files: (Attachment & { preview?: string | undefined })[]): void {
  files.forEach((file) => {
    if (file.preview) URL.revokeObjectURL(file.preview)
  })
}
function clearPending(): void {
  releasePreviews(pending.value)
  pending.value = []
}
function unsentAttachments(): Attachment[] {
  const stoppedIds = new Set(
    store.stoppedTurns
      .filter((turn) => turn.conversation_id === store.activeId)
      .flatMap((turn) => turn.attachments.map((file) => file.id)),
  )
  return store.attachments.filter((file) => !file.bound && !stoppedIds.has(file.id))
}
async function select(id: string): Promise<void> {
  if (busy.value) return
  picking.value = true
  try {
    await store.select(id)
    clearPending()
    text.value = ''
    pending.value = unsentAttachments()
  } catch (error: unknown) {
    showError(error)
  } finally {
    picking.value = false
  }
}
function newConversation(): void {
  if (busy.value) return
  clearPending()
  text.value = ''
  store.activeId = undefined
  store.turns = []
  store.attachments = []
}
async function removeConversation(id: string): Promise<void> {
  if (busy.value) return
  picking.value = true
  try {
    await consultationApi.delete(id)
    store.conversations = store.conversations.filter((row) => row.id !== id)
    store.stoppedTurns = store.stoppedTurns.filter((turn) => turn.conversation_id !== id)
    if (store.activeId === id) {
      clearPending()
      text.value = ''
      store.activeId = undefined
      store.turns = []
      store.attachments = []
    }
  } catch (error: unknown) {
    showError(error)
  } finally {
    picking.value = false
  }
}
function upload(event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement) || !target.files) return
  const files = [...target.files]
  target.value = ''
  void uploadFiles(files)
}
function pasteAttachments(event: ClipboardEvent): void {
  const clipboard = event.clipboardData
  if (!clipboard || busy.value || !configured.value) return
  const files = [...clipboard.items]
    .filter((item) => item.kind === 'file')
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null)
  if (!files.length) files.push(...clipboard.files)
  if (!files.length) return
  // 混合粘贴时保留文本框默认的文字粘贴行为。
  if (!clipboard.getData('text/plain')) event.preventDefault()
  void uploadFiles(files)
}
async function uploadFiles(files: File[]): Promise<void> {
  if (!files.length || busy.value || !configured.value || !store.options) return
  const policy = store.options.policy
  if (pending.value.length + files.length > policy.max_attachments) {
    message.warning(`最多上传 ${policy.max_attachments} 个附件`)
    return
  }
  if (
    files.some((file) => file.size > policy.max_file_mb * 1024 * 1024) ||
    files.reduce(
      (size, file) => size + file.size,
      pending.value.reduce((size, file) => size + file.size, 0),
    ) >
      policy.max_total_mb * 1024 * 1024
  ) {
    message.warning('附件超过大小限制')
    return
  }
  if (
    files.some((file) =>
      file.type === 'application/pdf'
        ? !store.model?.supports_pdf
        : !store.model?.supports_images ||
          !['image/png', 'image/jpeg', 'image/webp'].includes(file.type),
    )
  ) {
    message.warning('所选模型不支持此附件类型')
    return
  }
  uploading.value = true
  try {
    const id = store.activeId ?? (await store.create())
    for (const file of files) {
      const row = await consultationApi.upload(id, file)
      pending.value.push({
        ...row,
        preview: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
      })
    }
  } catch (error: unknown) {
    showError(error)
  } finally {
    uploading.value = false
  }
}
async function removeAttachment(file: Attachment): Promise<void> {
  if (busy.value) return
  uploading.value = true
  try {
    await consultationApi.removeAttachment(file.id)
    const row = pending.value.find((item) => item.id === file.id)
    if (row?.preview) URL.revokeObjectURL(row.preview)
    pending.value = pending.value.filter((item) => item.id !== file.id)
  } catch (error: unknown) {
    showError(error)
  } finally {
    uploading.value = false
  }
}
async function send(): Promise<void> {
  if (busy.value || !configured.value || (!text.value.trim() && !pending.value.length)) return
  const question = text.value
  const files = pending.value
  submitting.value = true
  text.value = ''
  pending.value = []
  let retainedInChat = false
  try {
    const result = await store.send(question.trim(), files)
    retainedInChat = result.saved || result.cancelled
    if (disposed) return
    if (result.rebuildRequired) message.warning('回答已保存，会话记忆将在下次对话时恢复')
    else if (result.cancelled && !result.saved) message.info('已停止生成')
  } catch (error: unknown) {
    if (!disposed) showError(error)
  } finally {
    if (retainedInChat || disposed) releasePreviews(files)
    else {
      text.value = question
      pending.value = files
    }
    submitting.value = false
  }
}
function keydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  if (!event.repeat) void send()
}
function turnAttachments(turn: Turn): Attachment[] {
  return store.attachments.filter((file) => turn.attachment_ids.includes(file.id))
}
function modelName(turn: Turn): string {
  const model = turn.config_snapshot.model
  return typeof model === 'object' &&
    model !== null &&
    'name' in model &&
    typeof model.name === 'string'
    ? model.name
    : '法律对话'
}
function retrievalLabel(turn: Turn): string | undefined {
  const method = turn.config_snapshot.retrieval_method
  if (method === 'hybrid') return '关键词与语义混合检索'
  if (method === 'keyword') return '关键词检索（暂无可用向量索引）'
  if (method === 'external') return '外部知识库'
  return undefined
}
function sourceUrl(source: Source): string | undefined {
  if (/^\/knowledge\/[\da-f-]{36}\/documents\/[\da-f-]{36}$/i.test(source.source)) {
    return source.source
  }
  try {
    const url = new URL(source.source)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined
  } catch {
    return undefined
  }
}
async function loadMore(): Promise<void> {
  try {
    const rows = await consultationApi.conversations(store.conversations.length)
    store.conversations.push(...rows)
  } catch (error: unknown) {
    showError(error)
  }
}
watch(
  () => [store.draftAnswer, store.draftReasoning, chatTurns.value.length],
  async () => {
    await nextTick()
    messageArea.value?.scrollTo({ top: messageArea.value.scrollHeight })
  },
)
onMounted(async () => {
  try {
    await store.initialize()
    if (store.activeId) {
      await store.refreshHistory()
      pending.value = unsentAttachments()
    }
  } catch (error: unknown) {
    showError(error)
  }
})
onBeforeUnmount(() => {
  disposed = true
  store.stop()
  clearPending()
})
</script>

<template>
  <section class="consultation-page" aria-label="法律对话">
    <div class="consultation-workspace">
      <aside class="conversation-sidebar" aria-label="对话历史">
        <NButton block secondary :disabled="busy" @click="newConversation"
          ><AppIcon name="plus" :size="17" />新建对话</NButton
        ><span class="conversation-label">对话历史</span
        ><NEmpty v-if="!store.conversations.length" size="small" description="还没有对话记录" />
        <div class="conversation-list">
          <div
            v-for="row in store.conversations"
            :key="row.id"
            class="conversation-item"
            :class="{ active: store.activeId === row.id }"
          >
            <button :disabled="busy" :title="row.title" @click="select(row.id)">
              <AppIcon name="chat" :size="16" /><span>{{ row.title }}</span></button
            ><NPopconfirm @positive-click="removeConversation(row.id)"
              ><template #trigger
                ><NButton
                  quaternary
                  circle
                  size="tiny"
                  :disabled="busy"
                  :aria-label="`删除 ${row.title}`"
                  ><AppIcon name="close" :size="13" /></NButton></template
              >删除此对话及其附件？</NPopconfirm
            >
          </div>
        </div>
        <NButton
          v-if="store.conversations.length >= 50"
          quaternary
          :disabled="busy"
          @click="loadMore"
          >加载更多</NButton
        >
      </aside>
      <div class="conversation-main">
        <div
          ref="messageArea"
          class="messages-area"
          aria-label="对话消息"
          :aria-busy="store.generating"
        >
          <NSpin v-if="store.loading" class="conversation-loading" />
          <div v-else-if="!configured" class="consultation-welcome">
            <AppIcon name="settings" :size="36" />
            <h2>先完成对话配置</h2>
            <p>在系统配置中设置可用对话模型。</p>
            <RouterLink to="/settings/consultation" class="text-link"
              >前往系统配置 <AppIcon name="arrow-right" :size="16"
            /></RouterLink>
          </div>
          <div v-else-if="!chatTurns.length && !store.generating" class="consultation-welcome">
            <h2>有什么法律问题想聊？</h2>
            <p>可以直接提问，也可以添加图片或 PDF。</p>
          </div>
          <article v-for="turn in chatTurns" :key="turn.key" class="conversation-turn">
            <div class="user-message">
              <div class="message-header">
                <span class="message-role">你</span>
                <MessageCopyButton :text="turn.user_text" label="复制提问" />
              </div>
              <p v-if="turn.user_text" class="message-text">{{ turn.user_text }}</p>
              <div v-if="turn.files.length" class="message-files">
                <MessageAttachment v-for="file in turn.files" :key="file.id" :file="file" />
              </div>
            </div>
            <div class="assistant-message">
              <div class="message-header">
                <span class="message-role"
                  ><AppIcon name="column" :size="18" />{{ turn.modelLabel
                  }}<span v-if="turn.stopped" class="live-label">已停止</span></span
                >
                <MessageCopyButton :text="turn.answer" label="复制回答" />
              </div>
              <ReasoningPanel v-if="turn.reasoning" :content="turn.reasoning" />
              <p v-if="turn.answer" class="message-text">{{ turn.answer }}</p>
              <details v-if="turn.sources.length" class="answer-sources">
                <summary>
                  知识来源 · {{ turn.sources.length }}
                  <span v-if="turn.retrieval"> · {{ turn.retrieval }}</span>
                </summary>
                <div v-for="(source, index) in turn.sources" :key="`${source.id}-${index}`">
                  <strong>[{{ index + 1 }}] {{ source.title }}</strong
                  ><a
                    v-if="sourceUrl(source)"
                    :href="sourceUrl(source)"
                    target="_blank"
                    rel="noopener noreferrer"
                    >{{ source.source }}</a
                  ><span v-else>{{ source.source }}</span>
                </div>
              </details>
            </div>
          </article>
          <article v-if="store.generating" class="conversation-turn live-turn">
            <div class="user-message">
              <div class="message-header">
                <span class="message-role">你</span>
                <MessageCopyButton :text="store.draftQuestion" label="复制提问" />
              </div>
              <p v-if="store.draftQuestion" class="message-text">{{ store.draftQuestion }}</p>
              <div v-if="store.draftAttachments.length" class="message-files">
                <MessageAttachment
                  v-for="file in store.draftAttachments"
                  :key="file.id"
                  :file="file"
                />
              </div>
            </div>
            <div class="assistant-message">
              <div class="message-header">
                <span class="message-role"
                  ><AppIcon name="column" :size="18" />{{ store.model?.name
                  }}<span class="live-label" role="status" aria-live="polite">{{
                    store.stopRequested
                      ? '已停止'
                      : store.compressingContext
                        ? '压缩上下文'
                        : store.draftReasoning && !store.draftAnswer
                          ? '思考中'
                          : '生成中'
                  }}</span></span
                >
                <MessageCopyButton :text="store.draftAnswer" label="复制当前回答" />
              </div>
              <ReasoningPanel
                v-if="store.draftReasoning"
                :content="store.draftReasoning"
                :active="!store.draftAnswer && !store.stopRequested"
              />
              <p v-if="store.draftAnswer" class="message-text">
                {{ store.draftAnswer
                }}<span v-if="!store.stopRequested" class="stream-caret" aria-hidden="true" />
              </p>
              <NSpin v-else-if="!store.stopRequested && !store.draftReasoning" size="small" />
            </div>
          </article>
        </div>
        <div class="consultation-composer">
          <div class="composer-surface">
            <div v-if="pending.length" class="pending-files">
              <div v-for="file in pending" :key="file.id" class="pending-file">
                <img v-if="file.preview" :src="file.preview" :alt="file.name" /><AppIcon
                  v-else
                  name="document"
                  :size="24"
                /><span>{{ file.name }}</span
                ><NButton
                  quaternary
                  circle
                  size="tiny"
                  :disabled="busy"
                  :aria-label="`移除 ${file.name}`"
                  @click="removeAttachment(file)"
                  ><AppIcon name="close" :size="14"
                /></NButton>
              </div>
            </div>
            <NInput
              v-model:value="text"
              class="dialog-input"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 8 }"
              :bordered="false"
              :theme-overrides="inputTheme"
              :input-props="{ onKeydown: keydown, enterkeyhint: 'send' }"
              maxlength="30000"
              :disabled="busy || !configured"
              placeholder="输入问题，或粘贴图片、PDF…"
              aria-label="对话内容，支持粘贴附件，Enter 发送，Shift + Enter 换行"
              @paste="pasteAttachments"
            />
            <div class="composer-actions">
              <div class="composer-attachments">
                <input
                  ref="input"
                  type="file"
                  :accept="accept"
                  multiple
                  hidden
                  @change="upload"
                /><NButton
                  quaternary
                  circle
                  :loading="uploading"
                  :disabled="busy || !configured || !accept"
                  aria-label="添加附件"
                  title="添加图片或 PDF"
                  @click="input?.click()"
                  ><AppIcon name="plus" :size="21"
                /></NButton>
              </div>
              <div class="composer-options">
                <ContextUsageIndicator
                  :model="store.model"
                  :conversation-id="store.activeId"
                  :history-version="store.turns.at(-1)?.sequence ?? 0"
                  :text="text"
                  :attachment-ids="pending.map((file) => file.id)"
                  :knowledge-enabled="store.knowledgeEnabled && !!text.trim()"
                  :busy="busy"
                />
                <NDropdown
                  trigger="click"
                  placement="top-end"
                  :options="modelOptions"
                  :disabled="busy || !modelOptions.length"
                  @select="selectModel"
                >
                  <NButton
                    class="composer-model"
                    quaternary
                    size="small"
                    :disabled="busy || !modelOptions.length"
                    aria-label="选择对话模型"
                    :title="store.model?.name ?? '选择对话模型'"
                  >
                    <span>{{ store.model?.name ?? '对话模型' }}</span
                    ><AppIcon name="chevron-down" :size="14" />
                  </NButton>
                </NDropdown>
                <NButton
                  class="knowledge-toggle"
                  :class="{ 'is-enabled': store.knowledgeEnabled }"
                  quaternary
                  size="small"
                  :disabled="busy"
                  :aria-pressed="store.knowledgeEnabled"
                  :title="store.knowledgeEnabled ? '关闭知识库' : '启用知识库'"
                  @click="toggleKnowledge"
                >
                  <AppIcon name="book" :size="16" /><span>知识库</span
                  ><span class="knowledge-dot" aria-hidden="true" />
                </NButton>
                <button
                  v-if="store.generating"
                  class="dialog-send"
                  type="button"
                  aria-label="停止生成"
                  title="停止生成"
                  :disabled="store.stopRequested"
                  @click="store.stop"
                >
                  <span class="stop-mark" aria-hidden="true" />
                </button>
                <button
                  v-else
                  class="dialog-send"
                  type="button"
                  :disabled="busy || !configured || (!text.trim() && !pending.length)"
                  aria-label="发送消息"
                  title="发送消息（Enter）"
                  @click="send"
                >
                  <AppIcon name="arrow-up" :size="20" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
