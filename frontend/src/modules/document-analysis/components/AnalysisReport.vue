<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NEmpty, NSelect, NTag } from 'naive-ui'
import type { DocumentCitation, Report } from '../types'
const props = defineProps<{ report: Report }>()
defineEmits<{ cite: [citation: DocumentCitation] }>()
const severity = ref<string | null>(null)
const statement = ref<string | null>(null)
const evidence = ref<string | null>(null)
const severityLabels = { high: '高风险', medium: '中风险', low: '低风险', info: '提示' }
const statementLabels = {
  contract_term: '合同约定',
  party_claim: '当事人主张',
  evidence_record: '证据记录',
  court_finding: '法院认定',
  analysis: '分析判断',
}
const evidenceLabels = { supported: '依据充分', limited: '依据有限', unverified: '待核实' }
const options = (labels: Record<string, string>): { label: string; value: string }[] =>
  Object.entries(labels).map(([value, label]) => ({ value, label }))
const findings = computed(() =>
  props.report.findings
    .filter(
      (item) =>
        (!severity.value || item.severity === severity.value) &&
        (!statement.value || item.statement_type === statement.value) &&
        (!evidence.value || item.evidence_status === evidence.value),
    )
    .sort(
      (a, b) =>
        ['high', 'medium', 'low', 'info'].indexOf(a.severity) -
        ['high', 'medium', 'low', 'info'].indexOf(b.severity),
    ),
)
</script>
<template>
  <section class="analysis-report">
    <h2>分析报告</h2>
    <p class="analysis-prose">{{ report.summary }}</p>
    <div class="analysis-filters">
      <NSelect
        v-model:value="severity"
        clearable
        :options="options(severityLabels)"
        placeholder="全部严重性"
        aria-label="按严重性筛选"
      />
      <NSelect
        v-model:value="statement"
        clearable
        :options="options(statementLabels)"
        placeholder="全部事实类型"
        aria-label="按事实类型筛选"
      />
      <NSelect
        v-model:value="evidence"
        clearable
        :options="options(evidenceLabels)"
        placeholder="全部依据状态"
        aria-label="按依据筛选"
      />
    </div>
    <NEmpty v-if="!findings.length" description="当前筛选下没有分析发现" />
    <article v-for="item in findings" :key="item.id" class="analysis-finding">
      <div class="analysis-tags">
        <NTag
          :type="
            item.severity === 'high' ? 'error' : item.severity === 'medium' ? 'warning' : 'default'
          "
          size="small"
          >{{ severityLabels[item.severity] }}</NTag
        ><NTag size="small">{{ statementLabels[item.statement_type] }}</NTag
        ><NTag size="small">{{ evidenceLabels[item.evidence_status] }}</NTag>
      </div>
      <h3>{{ item.title }}</h3>
      <p class="analysis-prose">{{ item.analysis }}</p>
      <p v-if="item.suggestion" class="analysis-prose">
        <strong>建议：</strong>{{ item.suggestion }}
      </p>
      <p v-if="item.uncertainty" class="analysis-prose">
        <strong>不确定性：</strong>{{ item.uncertainty }}
      </p>
      <div
        v-for="(citation, index) in item.document_citations"
        :key="`${citation.document_id}-${citation.span_id}-${index}`"
        class="analysis-citation"
      >
        <NButton text type="primary" @click="$emit('cite', citation)"
          >定位原文 {{ index + 1 }} · 第 {{ citation.revision }} 版</NButton
        >
        <blockquote>{{ citation.quote }}</blockquote>
      </div>
      <details
        v-for="(citation, index) in item.law_citations"
        :key="`${citation.source_id}-${index}`"
        class="analysis-law"
      >
        <summary>
          {{
            report.sources.find((source) => source.id === citation.source_id)?.title || '法律依据'
          }}
        </summary>
        <blockquote>{{ citation.quote }}</blockquote>
        <template
          v-for="source in report.sources.filter((source) => source.id === citation.source_id)"
          :key="source.id"
          ><p>来源：{{ source.source }}</p>
          <p class="analysis-prose">{{ source.content }}</p></template
        >
      </details>
    </article>
    <section v-if="report.timeline.length">
      <h3>时间线</h3>
      <ol>
        <li v-for="(item, index) in report.timeline" :key="index">{{ item }}</li>
      </ol>
    </section>
    <section v-if="report.missing_materials.length">
      <h3>待补充材料</h3>
      <ul>
        <li v-for="(item, index) in report.missing_materials" :key="index">{{ item }}</li>
      </ul>
    </section>
    <section v-if="report.limitations.length">
      <h3>分析限制</h3>
      <ul>
        <li v-for="(item, index) in report.limitations" :key="index">{{ item }}</li>
      </ul>
    </section>
    <section v-if="report.review_summary">
      <h3>复核结论</h3>
      <p class="analysis-prose">{{ report.review_summary }}</p>
    </section>
  </section>
</template>
