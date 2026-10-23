<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NSpin, NTag } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import ToolCallRecord from '../../../components/ToolCallRecord.vue'
import type { ToolStatus } from '../../../components/toolActivity'
import AnalysisReport from './AnalysisReport.vue'
import GeneratedFiles from '../../files/components/GeneratedFiles.vue'
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
function toolStatus(status: string): ToolStatus {
  if (status === 'running') return isActive(props.run.status) ? 'running' : 'interrupted'
  if (status === 'completed' || status === 'failed' || status === 'cancelled') return status
  return 'interrupted'
}
const callingTool = computed(
  () =>
    props.run.tool_calls.some((call) => call.status === 'running') || props.run.stage === 'files',
)
const workingLabel = computed(() => {
  if (props.run.stage === 'queued') return '正在准备分析'
  if (props.run.stage === 'intent') return '正在理解你的需求'
  if (props.run.stage === 'files') return '正在生成文件'
  return '正在阅读材料并核对依据'
})
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
      <div
        v-if="isActive(run.status) && !callingTool"
        class="analysis-chat-working"
        role="status"
        aria-live="polite"
      >
        <NSpin :size="16" /><span>{{ workingLabel }}</span>
      </div>
      <ToolCallRecord
        v-for="call in run.tool_calls"
        :key="call.id"
        :name="call.name"
        :status="toolStatus(call.status)"
        :duration-ms="call.duration_ms"
      />
      <ToolCallRecord
        v-if="run.stage === 'files' || run.files?.length"
        name="generate_files"
        :status="
          run.files?.length ? 'completed' : isActive(run.status) ? 'preparing' : 'interrupted'
        "
        :summary="run.files?.length ? `已生成 ${run.files.length} 个文件` : ''"
      />
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
      <GeneratedFiles :files="run.files ?? []" />
      <div v-if="run.status === 'cancelled'" class="analysis-muted">
        分析已停止，可以重新发送需求或继续本次分析。
      </div>
      <details v-if="run.steps.length" class="analysis-chat-process">
        <summary>分析过程</summary>
        <ol>
          <li v-for="step in run.steps" :key="step.id">
            {{ roles[step.agent] || '整理分析' }} · {{ stateLabels[step.status] || '处理中' }}
          </li>
        </ol>
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
