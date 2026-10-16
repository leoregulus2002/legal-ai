<script setup lang="ts">
import { computed } from 'vue'
import { NProgress, NTag } from 'naive-ui'
import type { KnowledgeDocument } from '../types'
const props = defineProps<{ document: KnowledgeDocument; compact?: boolean }>()
const stages = ['EXTRACTING', 'STRUCTURING', 'CHUNKING', 'VECTORIZING', 'COMPLETED']
const labels = ['文本提取', '结构解析', '文件切分', '向量化']
const current = computed(() => {
  const doc = props.document
  if (
    !['QUEUED', 'PROCESSING', 'FAILED'].includes(doc.status) &&
    ['QUEUED', 'PROCESSING', 'FAILED'].includes(doc.embedding_status)
  )
    return 3
  return stages.indexOf(doc.processing_stage)
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
      DISABLED: '未启用向量化',
      QUEUED: '等待向量化',
      PROCESSING: '向量化中',
      COMPLETED: '向量化完成',
      FAILED: '向量化中断',
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
          done: current > index && !(index === 3 && document.embedding_status === 'DISABLED'),
          active: current === index,
          disabled: index === 3 && document.embedding_status === 'DISABLED',
        }"
      >
        <span>{{ index + 1 }}</span
        >{{ label }}
      </li>
    </ol>
    <div class="kb-progress-row">
      <span>文件切分</span
      ><strong>{{ document.chunk_count }} / {{ document.chunk_total || '待确定' }}</strong>
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
      <span>{{ vectorLabel }}</span
      ><strong v-if="document.embedding_status !== 'DISABLED'"
        >{{ document.embedded_count }} / {{ document.chunk_count || '待切分' }}</strong
      ><NTag v-else size="small" :bordered="false">可稍后启用</NTag>
    </div>
    <NProgress
      v-if="document.embedding_status !== 'DISABLED'"
      type="line"
      :percentage="vectorPercent"
      :show-indicator="!compact"
      :height="6"
      :processing="document.embedding_status === 'PROCESSING'"
      :status="document.embedding_status === 'FAILED' ? 'error' : 'default'"
      color="#234a59"
    />
    <p v-if="!compact && document.embedding_dimensions" class="kb-muted">
      向量维度 {{ document.embedding_dimensions }} · 片段保留原文位置 · 可断点重试
    </p>
  </div>
</template>
