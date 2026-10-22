<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NProgress, NTag } from 'naive-ui'
import { ApiError } from '../../../api/client'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import type { VectorTask } from '../types'

const props = defineProps<{ task: VectorTask; stopping: boolean }>()
defineEmits<{ stop: []; refresh: [] }>()
const showError = useErrorMessage()

function showFailure(errorMessage: string | null): void {
  if (errorMessage) showError(new ApiError(errorMessage, 'http'))
}

const labels: Record<VectorTask['status'], string> = {
  RUNNING: '向量化进行中',
  STOPPING: '正在停止',
  STOPPED: '已停止',
  COMPLETED: '处理结束',
  FAILED: '任务中断',
}
const itemLabels: Record<string, string> = {
  PROCESSING: '处理中',
  COMPLETED: '已完成',
  SKIPPED: '已向量化，跳过',
  FAILED: '待重试',
  STOPPED: '已停止',
  PENDING: '等待处理',
}
const stages: Record<string, string> = {
  SCANNING: '查找下一批法规',
  WAITING_DOWNLOAD: '等待下载间隔结束',
  IMPORTING: '下载并导入原文',
  QUEUED: '等待解析',
  EXTRACTING: '提取正文',
  STRUCTURING: '结构化法条',
  VALIDATING: '校验数据',
  CHUNKING: '切分检索片段',
  VECTORIZING: '向量化',
  PUBLISHING: '发布检索索引',
  COMPLETED: '已完成',
  FAILED: '待重试',
}
const processed = computed(() => props.task.completed + props.task.skipped + props.task.failed)
const percentage = computed(() =>
  props.task.total ? Math.min(100, Math.floor((processed.value / props.task.total) * 100)) : 0,
)
const active = computed(() => ['RUNNING', 'STOPPING'].includes(props.task.status))
</script>

<template>
  <section class="public-law-vector-progress" aria-labelledby="vector-progress-title">
    <div class="public-law-vector-heading">
      <div>
        <h2 id="vector-progress-title">{{ labels[task.status] }}</h2>
        <p>
          <template v-if="task.request_mode === 'serial'"
            >线性请求 · 逐条完成下载、解析与向量化</template
          >
          <template v-else>
            并发请求 · 下载并发 1 · 解析与向量化并发 {{ task.concurrency }}
          </template>
          · 下载间隔 {{ task.download_delay_ms }} 毫秒 · 已有向量自动跳过
        </p>
      </div>
      <div class="public-law-import-actions">
        <NButton size="small" @click="$emit('refresh')">刷新进度</NButton>
        <NButton
          v-if="active"
          size="small"
          type="warning"
          :loading="stopping"
          :disabled="task.status === 'STOPPING'"
          @click="$emit('stop')"
        >
          {{ task.status === 'STOPPING' ? '等待当前请求结束' : '停止任务' }}
        </NButton>
      </div>
    </div>
    <NProgress
      v-if="task.total !== null"
      type="line"
      :percentage="percentage"
      :show-indicator="false"
    />
    <div class="public-law-vector-counts" aria-live="polite">
      <span>已处理 {{ processed }} / {{ task.total ?? '统计中' }} 条</span>
      <span>完成 {{ task.completed }}</span
      ><span>跳过 {{ task.skipped }}</span>
      <span>待重试 {{ task.failed }}</span>
      <span v-if="active">处理中 {{ task.current_items.length }} 条</span>
    </div>
    <div v-if="active" aria-live="polite">
      <p v-if="!task.current_items.length" class="public-law-vector-current">
        {{
          task.status === 'STOPPING'
            ? '正在停止任务'
            : (stages[task.stage ?? 'SCANNING'] ?? '正在查找法规')
        }}
      </p>
      <p v-for="item in task.current_items" :key="item.id" class="public-law-vector-current">
        <strong>{{ item.title }}</strong>
        <span>{{ stages[item.stage ?? 'IMPORTING'] ?? '处理中' }}</span>
        <span v-if="item.chunk_count > 0"
          >片段 {{ item.embedded_count }} / {{ item.chunk_count }}</span
        >
      </p>
    </div>
    <details v-if="task.recent.length">
      <summary>处理记录（最近 {{ task.recent.length }} 条）</summary>
      <ul class="public-law-import-items">
        <li v-for="item in task.recent" :key="item.id">
          <span>{{ item.title }}</span>
          <NTag size="small" :type="item.status === 'COMPLETED' ? 'success' : 'default'">{{
            itemLabels[item.status]
          }}</NTag>
          <NButton
            v-if="item.error_message"
            size="tiny"
            text
            @click="showFailure(item.error_message)"
          >
            查看原因
          </NButton>
          <RouterLink
            v-if="item.document_id"
            :to="`/knowledge/${task.knowledge_base_id}/documents/${item.document_id}`"
            >查看文档</RouterLink
          >
        </li>
      </ul>
    </details>
  </section>
</template>
