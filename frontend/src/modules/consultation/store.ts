import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError } from '../../api/client'
import { postEventStream } from '../../api/stream'
import { isToolActivity, type ToolActivity } from '../../components/toolActivity'
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
  type StoppedTurn,
  type Turn,
} from './types'

export const useConsultationStore = defineStore('consultation', () => {
  const options = ref<ConsultationOptions>()
  const conversations = ref<Conversation[]>([])
  const activeId = ref<string>()
  const turns = ref<Turn[]>([])
  const stoppedTurns = ref<StoppedTurn[]>([])
  const attachments = ref<Attachment[]>([])
  const generating = ref(false)
  const stopRequested = ref(false)
  const compressingContext = ref(false)
  const generatingFiles = ref(false)
  const draftToolCalls = ref<ToolActivity[]>([])
  const loading = ref(false)
  const draftAnswer = ref('')
  const draftReasoning = ref('')
  const draftQuestion = ref('')
  const draftAttachments = ref<Attachment[]>([])
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
    const useKnowledge = knowledgeEnabled.value && !!text.trim()
    if (useKnowledge && !options.value.policy.knowledge_base_ids?.length)
      throw new ApiError('请先在法律咨询模型中添加内部知识库', 'unknown')
    const promptId =
      options.value.prompts.find((prompt) => prompt.id === options.value?.policy.default_prompt_id)
        ?.id ?? null
    const id = activeId.value ?? (await create())
    const afterSequence = turns.value.at(-1)?.sequence ?? 0
    const modelName = model.value?.name ?? '法律对话'
    const fingerprint = JSON.stringify([
      selectedModel.value,
      promptId,
      text,
      files.map((f) => f.id),
      useKnowledge,
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
      knowledge_enabled: useKnowledge,
    }
    generating.value = true
    stopRequested.value = false
    compressingContext.value = false
    generatingFiles.value = false
    draftToolCalls.value = []
    draftQuestion.value = text
    draftAttachments.value = [...files]
    draftAnswer.value = ''
    draftReasoning.value = ''
    draftSources.value = []
    const requestController = new AbortController()
    controller = requestController
    let saved = false
    let rebuildRequired = false
    let failure: unknown
    try {
      await postEventStream(
        `/consultation/conversations/${id}/stream`,
        data,
        requestController.signal,
        (options.value.policy.request_timeout + 30) * 1000,
        (event) => {
          if (
            event.kind === 'status' &&
            isRecord(event.data) &&
            (event.data.phase === 'compressing_context' ||
              event.data.phase === 'generating' ||
              event.data.phase === 'generating_files')
          ) {
            compressingContext.value = event.data.phase === 'compressing_context'
            generatingFiles.value = event.data.phase === 'generating_files'
          } else if (event.kind === 'tool_call' && isToolActivity(event.data)) {
            const activity = event.data
            const index = draftToolCalls.value.findIndex((call) => call.id === activity.id)
            if (index < 0) draftToolCalls.value.push(activity)
            else draftToolCalls.value[index] = activity
          } else if (
            event.kind === 'answer_replace' &&
            isRecord(event.data) &&
            typeof event.data.text === 'string' &&
            typeof event.data.reasoning === 'string'
          ) {
            draftAnswer.value = event.data.text
            draftReasoning.value = event.data.reasoning
          } else if (
            event.kind === 'reasoning_delta' &&
            isRecord(event.data) &&
            typeof event.data.text === 'string'
          ) {
            compressingContext.value = false
            draftReasoning.value += event.data.text
          } else if (
            event.kind === 'delta' &&
            isRecord(event.data) &&
            typeof event.data.text === 'string'
          ) {
            compressingContext.value = false
            draftAnswer.value += event.data.text
          } else if (
            event.kind === 'sources' &&
            Array.isArray(event.data) &&
            event.data.every(isSource)
          )
            draftSources.value = event.data
          else if (event.kind === 'done' && isRecord(event.data) && isTurn(event.data.turn)) {
            generatingFiles.value = false
            compressingContext.value = false
            const turn = event.data.turn
            saved = true
            rebuildRequired = event.data.memory_status === 'rebuild_required'
            if (!turns.value.some((row) => row.id === turn.id)) turns.value.push(turn)
            const conversation = conversations.value.find((row) => row.id === id)
            if (conversation) {
              conversation.history_version = turn.sequence
              conversation.updated_at = turn.created_at
              if (typeof event.data.title === 'string' && event.data.title.trim())
                conversation.title = event.data.title
              conversations.value = [
                conversation,
                ...conversations.value.filter((row) => row.id !== id),
              ]
            }
            for (const file of attachments.value) {
              if (turn.attachment_ids.includes(file.id)) file.bound = true
            }
            for (const file of files) {
              if (!attachments.value.some((row) => row.id === file.id))
                attachments.value.push({ ...file, bound: true })
            }
            retry = undefined
          } else if (event.kind === 'error') {
            compressingContext.value = false
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
    } finally {
      compressingContext.value = false
      generatingFiles.value = false
      for (const call of draftToolCalls.value) {
        if (call.status === 'preparing' || call.status === 'running')
          call.status = requestController.signal.aborted ? 'cancelled' : 'interrupted'
      }
    }
    try {
      // 正常完成直接使用 done 的完整消息，不重复读取历史和附件。
      // 仅在 done 丢失时，以历史中的幂等 ID 确认结果，避免重复调用。
      if (!saved) {
        await refreshHistory()
        saved = turns.value.some((row) => row.request_id === requestId)
        if (saved) retry = undefined
        conversations.value = await consultationApi.conversations()
      }
    } catch (error: unknown) {
      failure ??= error
    } finally {
      if (saved) {
        stoppedTurns.value = stoppedTurns.value.filter((row) => row.request_id !== requestId)
      } else if (requestController.signal.aborted) {
        stoppedTurns.value = [
          ...stoppedTurns.value.filter((row) => row.request_id !== requestId),
          {
            request_id: requestId,
            conversation_id: id,
            after_sequence: afterSequence,
            user_text: draftQuestion.value,
            answer: draftAnswer.value,
            reasoning: draftReasoning.value,
            attachments: [...draftAttachments.value],
            sources: [...draftSources.value],
            model_name: modelName,
            tool_calls: draftToolCalls.value.map((call) => ({ ...call })),
          },
        ]
      }
      generating.value = false
      stopRequested.value = false
      compressingContext.value = false
      controller = undefined
      draftQuestion.value = ''
      draftAttachments.value = []
      draftAnswer.value = ''
      draftReasoning.value = ''
      draftSources.value = []
      draftToolCalls.value = []
    }
    const cancelled = requestController.signal.aborted
    if (failure && !saved && !cancelled) throw failure
    return { saved, rebuildRequired, cancelled }
  }
  function stop(): void {
    if (!controller || controller.signal.aborted) return
    stopRequested.value = true
    compressingContext.value = false
    generatingFiles.value = false
    for (const call of draftToolCalls.value) {
      if (call.status === 'preparing' || call.status === 'running') call.status = 'cancelled'
    }
    controller?.abort()
  }
  return {
    options,
    conversations,
    activeId,
    turns,
    stoppedTurns,
    attachments,
    generating,
    stopRequested,
    compressingContext,
    generatingFiles,
    draftToolCalls,
    loading,
    draftAnswer,
    draftReasoning,
    draftQuestion,
    draftAttachments,
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
