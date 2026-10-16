<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NTooltip } from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import type { ModelConfig } from '../../system-config/types'
import { consultationApi } from '../api'
import type { ContextUsage } from '../types'

const props = defineProps<{
  model: ModelConfig | undefined
  conversationId: string | undefined
  historyVersion: number
  text: string
  attachmentIds: string[]
  knowledgeEnabled: boolean
  busy: boolean
}>()

const showError = useErrorMessage()
const usage = ref<ContextUsage>()
const loading = ref(false)
const tooltipOpen = ref(false)
let failureNotified = false
const number = new Intl.NumberFormat('zh-CN')
const ratio = computed(() =>
  usage.value?.used_tokens != null && usage.value.context_tokens > 0
    ? usage.value.used_tokens / usage.value.context_tokens
    : undefined,
)
const percentage = computed(() =>
  ratio.value === undefined
    ? undefined
    : new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 1 }).format(
        ratio.value,
      ),
)
const capacity = computed(() => usage.value?.context_tokens ?? props.model?.context_tokens)
const reserved = computed(() => usage.value?.max_output_tokens ?? props.model?.max_output_tokens)
const remaining = computed(() =>
  usage.value?.used_tokens == null
    ? undefined
    : Math.max(
        0,
        usage.value.context_tokens - usage.value.used_tokens - usage.value.max_output_tokens,
      ),
)
const tone = computed(() => {
  if (ratio.value === undefined) return 'unknown'
  const current = usage.value
  if (
    current?.used_tokens != null &&
    current.used_tokens + current.max_output_tokens >= current.context_tokens
  )
    return 'danger'
  return ratio.value >= 0.8 ? 'warning' : 'normal'
})
const status = computed(() => {
  if (!props.model) return '请先选择对话模型'
  if (props.busy) return '对话处理中，完成后更新用量'
  if (loading.value) return '正在估算上下文…'
  const used = usage.value?.used_tokens
  if (used === null) return '待会话记忆恢复后更新'
  if (used === undefined) return '暂无上下文用量'
  return `预计已用 ${number.format(used)} Token（${percentage.value}）`
})

watch(
  () => [
    props.model,
    props.conversationId,
    props.historyVersion,
    props.text,
    props.attachmentIds,
    props.knowledgeEnabled,
    props.busy,
  ],
  (_value, _previous, onCleanup) => {
    usage.value = undefined
    loading.value = false
    const model = props.model
    if (!model || props.busy) return

    loading.value = true
    const controller = new AbortController()
    const data = {
      conversation_id: props.conversationId ?? null,
      model_id: model.id,
      text: props.text,
      attachment_ids: props.attachmentIds,
      knowledge_enabled: props.knowledgeEnabled,
    }
    // 输入停止后再估算；切换会话或继续输入时丢弃旧请求。
    const timer = setTimeout(async () => {
      try {
        const result = await consultationApi.contextUsage(data, controller.signal)
        if (controller.signal.aborted) return
        usage.value = result
        failureNotified = false
      } catch (error: unknown) {
        if (!controller.signal.aborted && !failureNotified) {
          failureNotified = true
          showError(error)
        }
      } finally {
        if (!controller.signal.aborted) loading.value = false
      }
    }, 500)
    onCleanup(() => {
      clearTimeout(timer)
      controller.abort()
    })
  },
  { immediate: true },
)
</script>

<template>
  <NTooltip placement="top" :show="tooltipOpen" :delay="150" @update:show="tooltipOpen = $event">
    <template #trigger>
      <NButton
        class="context-usage-trigger"
        :class="`context-usage--${tone}`"
        quaternary
        circle
        size="small"
        :aria-label="`上下文用量：${status}`"
        @focus="tooltipOpen = true"
        @blur="tooltipOpen = false"
        @keydown.esc="tooltipOpen = false"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle class="context-usage-track" cx="12" cy="12" r="8.5" stroke-width="2.5" />
          <circle
            v-if="ratio !== undefined"
            class="context-usage-fill"
            cx="12"
            cy="12"
            r="8.5"
            stroke="currentColor"
            stroke-width="2.5"
            stroke-linecap="round"
            pathLength="100"
            :stroke-dasharray="`${Math.min(100, Math.max(0, ratio * 100))} 100`"
            transform="rotate(-90 12 12)"
          />
          <circle cx="12" cy="12" r="2" fill="currentColor" />
        </svg>
      </NButton>
    </template>
    <div class="context-usage-tooltip">
      <strong>上下文用量{{ percentage ? ` · ${percentage}` : '' }}</strong>
      <span>{{ status }}</span>
      <span v-if="capacity != null">上下文上限 {{ number.format(capacity) }} Token</span>
      <span v-if="reserved != null">回复预留 {{ number.format(reserved) }} Token</span>
      <span v-if="remaining != null">剩余可用 {{ number.format(remaining) }} Token</span>
      <small>估算包含系统提示词、会话记忆、当前输入和附件。</small>
      <small v-if="knowledgeEnabled">尚未包含本次知识库检索资料。</small>
      <small>实际用量以模型服务统计为准。</small>
    </div>
  </NTooltip>
</template>

<style scoped>
.context-usage-trigger {
  flex-shrink: 0;
  color: #52755e;
}
.context-usage--unknown {
  color: #99968e;
}
.context-usage--warning {
  color: #b5812c;
}
.context-usage--danger {
  color: #bf554b;
}
.context-usage-track {
  stroke: currentColor;
  opacity: 0.2;
}
.context-usage-tooltip {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-width: min(19rem, 75vw);
  padding: 0.2rem;
  font-size: 0.78rem;
  line-height: 1.6;
  font-variant-numeric: tabular-nums;
}
.context-usage-tooltip small {
  opacity: 0.72;
  font-size: 0.72rem;
}
</style>
