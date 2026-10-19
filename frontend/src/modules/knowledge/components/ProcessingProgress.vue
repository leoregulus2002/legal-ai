<script setup lang="ts">
import { computed } from 'vue'
import { NProgress, NTag } from 'naive-ui'
import type { KnowledgeDocument } from '../types'
const props = defineProps<{ document: KnowledgeDocument; compact?: boolean }>()
const stages = ['EXTRACTING', 'STRUCTURING', 'VALIDATING', 'VECTORIZING', 'PUBLISHING']
const labels = ['文件解析', '法律条文结构化', '数据校验', '向量化处理', '自动发布']
const failed = computed(() => props.document.status === 'FAILED')
const current = computed(() => {
  const doc = props.document
  if (doc.status === 'PUBLISHED' || doc.processing_stage === 'COMPLETED') return stages.length
  const stage = failed.value ? doc.failed_stage : doc.processing_stage
  return stage === 'CHUNKING' ? 2 : stages.indexOf(stage ?? '')
})
const chunkPercent = computed(() =>
  props.document.chunk_total
    ? Math.round((props.document.chunk_count / props.document.chunk_total) * 100)
    : 0,
)
const vectorPercent = computed(() =>
  props.document.chunk_count
    ? Math.round((props.document.embedded_count / props.document.chunk_count) * 100)
    : 0,
)
const vectorLabel = computed(
  () =>
    ({
      DISABLED: '等待向量化配置',
      QUEUED: '等待向量化',
      PROCESSING: '向量化中',
      COMPLETED: '向量化完成',
      FAILED: props.document.failed_stage === 'VECTORIZING' ? '向量化中断，可重试' : '处理已中断',
    })[props.document.embedding_status],
)
</script>
<template>
  <div class="kb-progress" :class="{ 'kb-progress--compact': compact }" aria-live="polite">
    <ol v-if="!compact" class="kb-stages" aria-label="文档处理阶段">
      <li
        v-for="(label, index) in labels"
        :key="label"
        :class="{
          done: current > index,
          active: current === index && !failed,
          failed: current === index && failed,
        }"
      >
        <span>{{ index + 1 }}</span
        >{{ label }}
      </li>
    </ol>
    <div class="kb-progress-row">
      <span>检索片段</span>
      <strong>{{ document.chunk_count }} / {{ document.chunk_total || '待确定' }}</strong>
    </div>
    <NProgress
      type="line"
      :percentage="chunkPercent"
      :show-indicator="false"
      :height="6"
      :processing="document.processing_stage === 'CHUNKING'"
      color="#9b7b4f"
    />
    <div class="kb-progress-row">
      <span>{{ vectorLabel }}</span>
      <strong v-if="document.embedding_status !== 'DISABLED'">
        {{ document.embedded_count }} / {{ document.chunk_count || '待切分' }}
      </strong>
    </div>
    <NProgress
      v-if="document.embedding_status !== 'DISABLED'"
      type="line"
      :percentage="vectorPercent"
      :show-indicator="!compact"
      :height="6"
      :processing="document.embedding_status === 'PROCESSING'"
      :status="failed ? 'error' : 'default'"
      color="#234a59"
    />
    <div v-if="!compact" class="kb-inline">
      <NTag v-if="document.status === 'PUBLISHED'" type="success" :bordered="false">
        已发布 · 可全文、法条与向量检索
      </NTag>
      <NTag v-else-if="document.status === 'WITHDRAWN'" :bordered="false">已撤回检索</NTag>
      <NTag v-else-if="failed" type="error" :bordered="false">未发布 · 支持重试</NTag>
      <span v-if="document.embedding_dimensions" class="kb-muted">
        向量维度 {{ document.embedding_dimensions }} · 片段保留原文位置
      </span>
    </div>
  </div>
</template>
