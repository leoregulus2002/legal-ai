<script setup lang="ts">
import { computed } from 'vue'
import AppIcon, { type IconName } from './AppIcon.vue'
import type { ToolStatus } from './toolActivity'

const props = defineProps<{
  name: string
  status: ToolStatus
  summary?: string
  durationMs?: number | null
}>()
const tools: Record<string, { label: string; completed: string; icon: IconName }> = {
  generate_files: { label: '文件生成', completed: '已生成文件', icon: 'document' },
  knowledge_search: { label: '内部知识库检索', completed: '已检索内部知识库', icon: 'book' },
  document_read_spans: { label: '文书原文读取', completed: '已读取文书原文', icon: 'book' },
  document_search: { label: '文书段落检索', completed: '已检索文书段落', icon: 'search' },
  document_compare: { label: '文书差异比较', completed: '已比较文书差异', icon: 'document' },
  law_search: { label: '法律法规检索', completed: '已检索法律法规', icon: 'search' },
  law_get_article: { label: '法条原文核对', completed: '已核对法条原文', icon: 'book' },
  analysis_read_parent: { label: '历史分析查阅', completed: '已查阅历史分析', icon: 'book' },
}
const tool = computed(() => tools[props.name])
const label = computed(() => tool.value?.label ?? props.name)
const busy = computed(() => props.status === 'preparing' || props.status === 'running')
const title = computed(() => {
  if (busy.value) return `正在调用 ${label.value} 工具`
  if (props.status === 'completed') return tool.value?.completed ?? `已调用 ${label.value} 工具`
  if (props.status === 'cancelled') return `${label.value} · 已停止`
  return `${label.value} · 未完成`
})
const state = computed(() => {
  if (props.status === 'preparing')
    return props.name === 'generate_files' ? '正在准备文件内容' : '准备中'
  if (props.status === 'running') return '执行中'
  if (props.status === 'completed') return '已完成'
  if (props.status === 'cancelled') return '已停止'
  return '未完成'
})
</script>

<template>
  <details class="tool-call-record">
    <summary>
      <AppIcon
        :name="busy ? 'refresh' : (tool?.icon ?? 'document')"
        :size="15"
        :class="{ 'tool-call-record-spinner': busy }"
      />
      <span role="status" aria-live="polite">{{ title }}</span>
      <AppIcon name="chevron-right" :size="13" class="tool-call-record-chevron" />
    </summary>
    <dl>
      <div>
        <dt>工具</dt>
        <dd>{{ label }}</dd>
      </div>
      <div>
        <dt>状态</dt>
        <dd>{{ state }}</dd>
      </div>
      <div v-if="status === 'completed' && summary">
        <dt>结果</dt>
        <dd>{{ summary }}</dd>
      </div>
      <div v-if="durationMs != null && !busy">
        <dt>用时</dt>
        <dd>{{ (durationMs / 1000).toFixed(1) }} 秒</dd>
      </div>
    </dl>
  </details>
</template>

<style scoped>
.tool-call-record {
  margin: 0.85rem 0;
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.6;
}
.tool-call-record summary {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: fit-content;
  max-width: 100%;
  border-radius: 4px;
  cursor: pointer;
  list-style: none;
}
.tool-call-record summary::-webkit-details-marker {
  display: none;
}
.tool-call-record summary:hover {
  color: var(--ink);
}
.tool-call-record summary:focus-visible {
  outline: 2px solid var(--bronze);
  outline-offset: 4px;
}
.tool-call-record summary > svg {
  flex-shrink: 0;
}
.tool-call-record summary > span {
  overflow-wrap: anywhere;
}
.tool-call-record-chevron {
  transition: transform 0.15s ease;
}
.tool-call-record[open] .tool-call-record-chevron {
  transform: rotate(90deg);
}
.tool-call-record dl {
  margin: 0.65rem 0 0 0.4rem;
  padding: 0.15rem 0 0.15rem 1rem;
  border-left: 1px solid var(--line);
  font-size: 0.78rem;
}
.tool-call-record dl > div {
  display: flex;
  gap: 0.9rem;
  margin: 0.25rem 0;
}
.tool-call-record dt {
  flex-shrink: 0;
}
.tool-call-record dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.tool-call-record-spinner {
  animation: tool-call-spin 1.2s linear infinite;
}
@keyframes tool-call-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .tool-call-record-spinner {
    animation: none;
  }
  .tool-call-record-chevron {
    transition: none;
  }
}
</style>
