import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError } from '../../api/client'
import { postEventStream } from '../../api/stream'
import { consultationApi } from './api'
import {
  isRecord,
  isSource,
  isTurn,
  type Attachment,
  type ConsultationOptions,
  type Conversation,
  type GenerateInput,
  type Source,
  type Turn,
} from './types'

export const useConsultationStore = defineStore('consultation', () => {
  const options = ref<ConsultationOptions>()
  const conversations = ref<Conversation[]>([])
  const activeId = ref<string>()
  const turns = ref<Turn[]>([])
  const attachments = ref<Attachment[]>([])
  const generating = ref(false)
  const loading = ref(false)
  const draftAnswer = ref('')
  const draftQuestion = ref('')
  const draftSources = ref<Source[]>([])
  const selectedModel = ref<string | null>(null)
  const knowledgeEnabled = ref(false)
  let controller: AbortController | undefined
  let retry: { conversationId: string; fingerprint: string; requestId: string } | undefined
  const model = computed(() => options.value?.models.find((row) => row.id === selectedModel.value))

  async function initialize(): Promise<void> {
    loading.value = true
    try {
      const [settings, rows] = await Promise.all([
        consultationApi.options(),
        consultationApi.conversations(),
      ])
      options.value = settings
      conversations.value = rows
      if (!settings.models.some((m) => m.id === selectedModel.value))
        selectedModel.value = settings.policy.default_model_id ?? settings.models[0]?.id ?? null
    } finally {
      loading.value = false
    }
  }
  async function refreshHistory(): Promise<void> {
    if (!activeId.value) return
    const id = activeId.value
    const rows: Turn[] = []
    let after = 0
    while (true) {
      const batch = await consultationApi.turns(id, after)
      rows.push(...batch)
      if (batch.length < 100) break
      after = batch[batch.length - 1]!.sequence
    }
    const files = await consultationApi.attachments(id)
    if (activeId.value === id) {
      turns.value = rows
      attachments.value = files
    }
  }
  async function select(id: string): Promise<void> {
    if (generating.value) return
    activeId.value = id
    turns.value = []
    attachments.value = []
    loading.value = true
    try {
      await refreshHistory()
    } finally {
      loading.value = false
    }
  }
  async function create(): Promise<string> {
    const row = await consultationApi.create()
    conversations.value.unshift(row)
    activeId.value = row.id
    turns.value = []
    attachments.value = []
    return row.id
  }
  async function send(
    text: string,
    files: Attachment[],
  ): Promise<{ saved: boolean; rebuildRequired: boolean; cancelled: boolean }> {
    if (!selectedModel.value || generating.value || !options.value)
      throw new ApiError('请先选择对话模型', 'unknown')
    const promptId =
      options.value.prompts.find((prompt) => prompt.id === options.value?.policy.default_prompt_id)
        ?.id ?? null
    const id = activeId.value ?? (await create())
    const fingerprint = JSON.stringify([
      selectedModel.value,
      promptId,
      text,
      files.map((f) => f.id),
      knowledgeEnabled.value,
    ])
    const requestId =
      retry?.conversationId === id && retry.fingerprint === fingerprint
        ? retry.requestId
        : crypto.randomUUID()
    retry = { conversationId: id, fingerprint, requestId }
    const data: GenerateInput = {
      request_id: requestId,
      model_id: selectedModel.value,
      prompt_id: promptId,
      text,
      attachment_ids: files.map((file) => file.id),
      knowledge_enabled: knowledgeEnabled.value,
    }
    generating.value = true
    draftQuestion.value = text
    draftAnswer.value = ''
    draftSources.value = []
    controller = new AbortController()
    let saved = false
    let rebuildRequired = false
    let failure: unknown
    try {
      await postEventStream(
        `/consultation/conversations/${id}/stream`,
        data,
        controller.signal,
        (options.value.policy.request_timeout + 15) * 1000,
        (event) => {
          if (event.kind === 'delta' && isRecord(event.data) && typeof event.data.text === 'string')
            draftAnswer.value += event.data.text
          else if (
            event.kind === 'sources' &&
            Array.isArray(event.data) &&
            event.data.every(isSource)
          )
            draftSources.value = event.data
          else if (event.kind === 'done' && isRecord(event.data) && isTurn(event.data.turn)) {
            const turn = event.data.turn
            saved = true
            rebuildRequired = event.data.memory_status === 'rebuild_required'
            if (!turns.value.some((row) => row.id === turn.id)) turns.value.push(turn)
            retry = undefined
          } else if (event.kind === 'error') {
            const message =
              isRecord(event.data) && typeof event.data.message === 'string'
                ? event.data.message
                : '生成暂时不可用，请稍后重试'
            throw new ApiError(message, 'unknown')
          }
        },
      )
      if (!saved) throw new ApiError('回答连接中断，请重新发送', 'network')
    } catch (error: unknown) {
      failure = error
    }
    const cancelled = controller.signal.aborted
    // 提交成功但 done 丢失时，以历史中的幂等 ID 确认结果，避免重复调用。
    try {
      await refreshHistory()
      saved ||= turns.value.some((row) => row.request_id === requestId)
      if (saved) retry = undefined
      conversations.value = await consultationApi.conversations()
    } catch (error: unknown) {
      failure ??= error
    } finally {
      generating.value = false
      controller = undefined
      draftQuestion.value = ''
      draftAnswer.value = ''
      draftSources.value = []
    }
    if (failure && !saved && !cancelled) throw failure
    return { saved, rebuildRequired, cancelled }
  }
  function stop(): void {
    controller?.abort()
  }
  return {
    options,
    conversations,
    activeId,
    turns,
    attachments,
    generating,
    loading,
    draftAnswer,
    draftQuestion,
    draftSources,
    selectedModel,
    knowledgeEnabled,
    model,
    initialize,
    select,
    create,
    send,
    stop,
    refreshHistory,
  }
})
