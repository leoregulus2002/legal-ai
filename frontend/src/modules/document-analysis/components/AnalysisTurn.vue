<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NSpin, NTag } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import AnalysisReport from './AnalysisReport.vue'
import { intentOptions, isActive, statusLabels } from '../types'
import type { DocumentCitation, DocumentView, RunView } from '../types'

const props = defineProps<{
  run: RunView
  documents: DocumentView[]
  latest: boolean
  actionBusy: boolean
}>()
defineEmits<{ cite: [citation: DocumentCitation]; cancel: []; retry: []; export: [] }>()
const expanded = ref(props.latest)
const files = computed(() =>
  props.run.document_ids
    .map((id) => props.documents.find((doc) => doc.id === id))
    .filter((doc): doc is DocumentView => !!doc),
)
const intentLabel = computed(
  () =>
    intentOptions.find((item) => item.value === props.run.intent?.primary_intent)?.label ??
    '文书分析',
)
const roles: Record<string, string> = {
  intent: '理解需求',
  research: '查找法律依据',
  contract: '合同分析',
  litigation: '诉讼分析',
  judgment: '裁判文书分析',
  review: '核对事实与引用',
  comparison: '比较文书',
}
const stateLabels: Record<string, string> = {
  running: '进行中',
  completed: '已完成',
  failed: '未完成',
  cancelled: '已停止',
  interrupted: '等待恢复',
}
const toolLabel = (name: string): string =>
  ({
    document_read_spans: '阅读文书原文',
    document_search: '查找相关段落',
    document_compare: '比较文书差异',
    knowledge_search: '检索内部资料',
    law_search: '检索法律法规',
    law_get_article: '核对法条原文',
    analysis_read_parent: '查阅上轮分析',
  })[name] ?? '查询外部资料'
</script>

<template>
  <article class="analysis-chat-turn">
    <div class="analysis-chat-user">
      <p>{{ run.instruction }}</p>
      <div v-if="files.length" class="analysis-chat-user-files">
        <span v-for="doc in files" :key="doc.id"
          ><AppIcon name="document" :size="14" />{{ doc.filename }}</span
        >
      </div>
    </div>
    <template v-for="(entry, index) in run.clarification_history" :key="index">
      <div class="analysis-chat-question">{{ entry.question }}</div>
      <div class="analysis-chat-user">
        <p>{{ entry.answer }}</p>
      </div>
    </template>
    <div class="analysis-chat-assistant">
      <div class="analysis-chat-assistant-label">
        <AppIcon name="column" :size="21" /><strong>法律文书助手</strong
        ><span>{{ statusLabels[run.status] }}</span>
      </div>
      <div v-if="run.intent" class="analysis-chat-understanding">
        <span>{{ intentLabel }}</span
        ><span>{{ run.intent.perspective || '中立分析' }}</span
        ><span>{{ run.intent.jurisdiction || '中国大陆' }}</span>
      </div>
      <div v-if="isActive(run.status)" class="analysis-chat-working" role="status">
        <NSpin :size="16" /><span>{{
          run.stage === 'queued'
            ? '正在准备分析'
            : run.stage === 'intent'
              ? '正在理解你的需求'
              : '正在阅读材料、调用工具并核对依据'
        }}</span>
      </div>
      <p v-if="run.status === 'needs_input' && run.clarification" class="analysis-prose">
        {{ run.clarification }}
      </p>
      <template v-if="run.report">
        <p v-if="!expanded" class="analysis-prose">{{ run.report.summary }}</p>
        <AnalysisReport v-if="expanded" :report="run.report" @cite="$emit('cite', $event)" />
        <div class="analysis-chat-answer-actions">
          <NButton text size="small" @click="expanded = !expanded">{{
            expanded ? '收起详细分析' : '展开详细分析与依据'
          }}</NButton
          ><NButton text size="small" @click="$emit('export')">导出报告</NButton>
        </div>
      </template>
      <div v-if="run.status === 'cancelled'" class="analysis-muted">
        分析已停止，可以重新发送需求或继续本次分析。
      </div>
      <details v-if="run.steps.length || run.tool_calls.length" class="analysis-chat-process">
        <summary>
          分析过程<span v-if="run.tool_calls.length">
            · 已调用工具 {{ run.tool_calls.length }} 次</span
          >
        </summary>
        <ol>
          <li v-for="step in run.steps" :key="step.id">
            {{ roles[step.agent] || '整理分析' }} · {{ stateLabels[step.status] || '处理中' }}
          </li>
        </ol>
        <ul v-if="run.tool_calls.length">
          <li v-for="call in run.tool_calls" :key="call.id">
            {{ toolLabel(call.name) }} · {{ stateLabels[call.status] || '处理中' }}
          </li>
        </ul>
      </details>
      <div class="analysis-chat-answer-actions">
        <NButton
          v-if="isActive(run.status)"
          size="small"
          :loading="actionBusy"
          @click="$emit('cancel')"
          >停止分析</NButton
        >
        <NButton
          v-if="['failed', 'cancelled', 'partial'].includes(run.status)"
          size="small"
          :loading="actionBusy"
          @click="$emit('retry')"
          >{{ run.status === 'partial' ? '继续完善分析' : '重新分析' }}</NButton
        >
        <NTag v-if="run.status === 'failed'" size="small" type="warning">本次未完成</NTag>
      </div>
    </div>
  </article>
</template>
