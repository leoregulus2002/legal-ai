<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NDropdown, NEmpty, NInput, NPopconfirm, NSpin, useMessage } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { consultationApi } from '../api'
import { useConsultationStore } from '../store'
import type { Attachment, Source, Turn } from '../types'

const store = useConsultationStore()
const message = useMessage()
const showError = useErrorMessage()
const text = ref('')
const pending = ref<(Attachment & { preview?: string | undefined })[]>([])
const uploading = ref(false)
const picking = ref(false)
const input = ref<HTMLInputElement>()
const messageArea = ref<HTMLElement>()
const modelOptions = computed(
  () => store.options?.models.map((m) => ({ label: m.name, key: m.id })) ?? [],
)
const configured = computed(() => modelOptions.value.length > 0)
const inputTheme = { color: 'transparent', colorFocus: 'transparent', boxShadowFocus: 'none' }
const busy = computed(() => store.generating || uploading.value || picking.value || store.loading)
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

function clearPending(): void {
  pending.value.forEach((file) => {
    if (file.preview) URL.revokeObjectURL(file.preview)
  })
  pending.value = []
}
async function select(id: string): Promise<void> {
  if (busy.value) return
  picking.value = true
  try {
    await store.select(id)
    clearPending()
    text.value = ''
    pending.value = store.attachments.filter((file) => !file.bound)
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
async function upload(event: Event): Promise<void> {
  const target = event.target
  if (!(target instanceof HTMLInputElement) || !target.files || busy.value || !store.options) return
  const files = [...target.files]
  target.value = ''
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
  if (store.knowledgeEnabled && !text.value.trim()) {
    message.warning('请填写文字问题以查询知识库')
    return
  }
  try {
    const result = await store.send(text.value.trim(), pending.value)
    if (result.saved) {
      text.value = ''
      clearPending()
    }
    if (result.rebuildRequired) message.warning('回答已保存，会话记忆将在下次对话时恢复')
    else if (result.cancelled && !result.saved) message.info('已停止生成')
  } catch (error: unknown) {
    showError(error)
  }
}
function keydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}
async function download(file: Attachment): Promise<void> {
  try {
    const blob = await consultationApi.downloadAttachment(file.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.name
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error: unknown) {
    showError(error)
  }
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
function sourceUrl(source: Source): string | undefined {
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
  () => [store.draftAnswer, store.turns.length],
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
      pending.value = store.attachments.filter((file) => !file.bound)
    }
  } catch (error: unknown) {
    showError(error)
  }
})
onBeforeUnmount(() => {
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
            <button :disabled="busy" @click="select(row.id)">
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
          <div v-else-if="!store.turns.length && !store.generating" class="consultation-welcome">
            <h2>有什么法律问题想聊？</h2>
            <p>可以直接提问，也可以添加图片或 PDF。</p>
          </div>
          <article v-for="turn in store.turns" :key="turn.id" class="conversation-turn">
            <div class="user-message">
              <span class="message-role">你</span>
              <p class="message-text">{{ turn.user_text }}</p>
              <div v-if="turn.attachment_ids.length" class="message-files">
                <NButton
                  v-for="file in turnAttachments(turn)"
                  :key="file.id"
                  size="small"
                  secondary
                  @click="download(file)"
                  ><AppIcon name="document" :size="15" />{{ file.name }}</NButton
                >
              </div>
            </div>
            <div class="assistant-message">
              <span class="message-role"
                ><AppIcon name="column" :size="18" />{{ modelName(turn) }}</span
              >
              <p class="message-text">{{ turn.answer }}</p>
              <details v-if="turn.sources.length" class="answer-sources">
                <summary>知识来源 · {{ turn.sources.length }}</summary>
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
              <span class="message-role">你</span>
              <p class="message-text">{{ store.draftQuestion || '附件对话' }}</p>
            </div>
            <div class="assistant-message">
              <span class="message-role"
                ><AppIcon name="column" :size="18" />{{ store.model?.name
                }}<span class="live-label">生成中</span></span
              >
              <p v-if="store.draftAnswer" class="message-text">
                {{ store.draftAnswer }}<span class="stream-caret" aria-hidden="true" />
              </p>
              <NSpin v-else size="small" />
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
              maxlength="30000"
              :disabled="busy || !configured"
              placeholder="输入问题，或添加图片、PDF…"
              aria-label="对话内容，Enter 发送，Shift + Enter 换行"
              @keydown="keydown"
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
                  @click="store.knowledgeEnabled = !store.knowledgeEnabled"
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
                  title="发送消息"
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
