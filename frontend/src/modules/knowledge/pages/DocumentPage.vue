<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NCheckbox,
  NEmpty,
  NInput,
  NInputNumber,
  NModal,
  NPagination,
  NPopconfirm,
  NSelect,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  useMessage,
} from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { configApi } from '../../system-config/api'
import { knowledgeApi } from '../api'
import ProcessingProgress from '../components/ProcessingProgress.vue'
import StructureEditor from '../components/StructureEditor.vue'
import type {
  AuditEntry,
  Comparison,
  CorrectionInput,
  DocumentDetail,
  KnowledgeDocument,
  LegalMetadata,
  LegalStatus,
  Segment,
  SourceKind,
  StructureNode,
  VersionCandidate,
} from '../types'
import { categoryLabels, isProcessing, legalLabels, sourceLabels, statusLabels } from '../types'
import '../styles.css'
const route = useRoute()
const router = useRouter()
const baseId = computed(() => String(route.params.baseId))
const documentId = computed(() => String(route.params.documentId))
const detail = ref<DocumentDetail>()
const document = computed(() => detail.value?.document)
const loading = ref(false)
const saving = ref(false)
const activeTab = ref('review')
const nodes = ref<StructureNode[]>([])
const acknowledged = ref<string[]>([])
const metadata = reactive<LegalMetadata>({
  title: '',
  authority: '',
  document_number: '',
  promulgated_on: null,
  effective_on: null,
  version_label: '',
  category: 'UNCLASSIFIED',
  region: '',
})
const review = reactive({
  source_kind: 'USER_UPLOADED' as SourceKind,
  source_url: '',
  source_note: '',
  verification_note: '',
  legal_status: 'UNKNOWN' as LegalStatus,
  version_confirmed: false,
})
const reason = ref('')
const selectedModel = ref<string | null>(null)
const models = ref<{ label: string; value: string }[]>([])
const segments = ref<Segment[]>([])
const segmentTotal = ref(0)
const segmentPage = ref(1)
const versions = ref<VersionCandidate[]>([])
const comparison = ref<Comparison>()
const comparing = ref(false)
const audit = ref<AuditEntry[]>([])
const auditPage = ref(1)
const operation = ref<'publish' | 'withdraw' | 'reparse' | null>(null)
const operationReason = ref('')
const sourcePage = ref(1)
const sourceMapPage = ref(1)
const historyRevision = ref<number | null>(null)
const historical = ref<DocumentDetail>()
const actionLabels = { publish: '审核并发布', withdraw: '撤回发布', reparse: '重新解析' }
const showError = useErrorMessage()
const message = useMessage()
const sourceOptions = Object.entries(sourceLabels).map(([value, label]) => ({ value, label }))
const legalOptions = Object.entries(legalLabels).map(([value, label]) => ({ value, label }))
const busy = computed(() => !!document.value && isProcessing(document.value))
const disabled = computed(() => busy.value || saving.value || loading.value)
const textChars = computed(() => Array.from(detail.value?.result?.text ?? ''))
const sourceExcerpt = computed(() =>
  textChars.value.slice((sourcePage.value - 1) * 5000, sourcePage.value * 5000).join(''),
)
const sourceSpans = computed(() => detail.value?.result?.spans ?? [])
const visibleSpans = computed(() =>
  sourceSpans.value.slice((sourceMapPage.value - 1) * 100, sourceMapPage.value * 100),
)
const auditLabels: Record<string, string> = {
  UPLOAD: '上传文档',
  PARSE: '规则解析完成',
  PARSE_FAILED: '解析未完成',
  CORRECT: '人工修订',
  PUBLISH: '审核发布',
  WITHDRAW: '撤回发布',
  REPARSE: '重新解析',
  VECTORIZE: '发起向量化',
  EMBED_COMPLETE: '向量化完成',
  EMBED_FAILED: '向量化未完成',
  DELETE_DOCUMENT: '删除文档',
}
const dirty = computed(() => {
  if (!detail.value?.result || !document.value) return false
  return (
    JSON.stringify(nodes.value) !== JSON.stringify(detail.value.result.nodes) ||
    JSON.stringify(metadata) !== JSON.stringify(detail.value.result.metadata) ||
    reason.value.trim().length > 0 ||
    acknowledged.value.join('|') !== detail.value.acknowledged_issues.join('|') ||
    Object.entries(review).some(
      ([key, value]) => value !== document.value?.[key as keyof KnowledgeDocument],
    )
  )
})
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let refreshing = false
let pollFailed = false
function apply(result: DocumentDetail): void {
  detail.value = result
  nodes.value = structuredClone(result.result?.nodes ?? [])
  if (result.result) Object.assign(metadata, result.result.metadata)
  Object.assign(review, {
    source_kind: result.document.source_kind,
    source_url: result.document.source_url,
    source_note: result.document.source_note,
    verification_note: result.document.verification_note,
    legal_status: result.document.legal_status,
    version_confirmed: result.document.version_confirmed,
  })
  acknowledged.value = [...result.acknowledged_issues]
  reason.value = ''
  selectedModel.value = result.document.embedding_model_id
}
function schedule(): void {
  clearTimeout(timer)
  if (!disposed && document.value && isProcessing(document.value))
    timer = setTimeout(
      () => {
        void poll()
      },
      pollFailed ? 5000 : 1500,
    )
}
async function poll(): Promise<void> {
  if (refreshing || disposed) return
  refreshing = true
  try {
    const row = await knowledgeApi.status(baseId.value, documentId.value)
    if (disposed || !detail.value) return
    pollFailed = false
    const changed = row.revision !== detail.value.document.revision || !isProcessing(row)
    if (changed) {
      const next = await knowledgeApi.detail(baseId.value, documentId.value)
      if (disposed) return
      apply(next)
      if (activeTab.value === 'segments') await loadSegments()
    } else {
      detail.value.document = row
    }
    schedule()
  } catch (error: unknown) {
    if (!disposed && !pollFailed) showError(error)
    pollFailed = true
  } finally {
    refreshing = false
    schedule()
  }
}
async function load(): Promise<void> {
  clearTimeout(timer)
  loading.value = true
  try {
    const result = await knowledgeApi.detail(baseId.value, documentId.value)
    if (disposed) return
    apply(result)
    schedule()
  } catch (error: unknown) {
    if (!disposed) showError(error)
  } finally {
    loading.value = false
  }
}
async function save(): Promise<void> {
  if (!document.value || !detail.value?.result) return
  if (!reason.value.trim()) {
    message.warning('请填写本次校正或审核说明')
    return
  }
  saving.value = true
  try {
    const payload: CorrectionInput = {
      expected_revision: document.value.revision,
      metadata: { ...metadata },
      nodes: nodes.value,
      ...review,
      acknowledged_issues: acknowledged.value,
      reason: reason.value.trim(),
    }
    apply(await knowledgeApi.correct(baseId.value, documentId.value, payload))
    sourcePage.value = 1
    schedule()
    message.success('修订已保存，并已记录审计')
  } catch (error: unknown) {
    showError(error)
  } finally {
    saving.value = false
  }
}
function setAcknowledged(id: string, checked: boolean): void {
  acknowledged.value = checked
    ? [...new Set([...acknowledged.value, id])]
    : acknowledged.value.filter((value) => value !== id)
}
function requestOperation(action: 'publish' | 'withdraw' | 'reparse'): void {
  if (dirty.value) {
    message.warning('请先保存当前校正内容')
    return
  }
  operation.value = action
  operationReason.value = ''
}
async function runOperation(): Promise<void> {
  if (!document.value || !operation.value) return
  if (!operationReason.value.trim()) {
    message.warning('请填写操作说明')
    return
  }
  saving.value = true
  try {
    await knowledgeApi.action(
      baseId.value,
      documentId.value,
      operation.value,
      document.value.revision,
      operationReason.value.trim(),
    )
    operation.value = null
    await load()
    message.success('操作已保存')
  } catch (error: unknown) {
    showError(error)
  } finally {
    saving.value = false
  }
}
async function vectorize(): Promise<void> {
  if (!document.value || !selectedModel.value) {
    message.warning('请选择 Embedding 模型')
    return
  }
  if (dirty.value) {
    message.warning('请先保存当前校正内容')
    return
  }
  saving.value = true
  try {
    await knowledgeApi.vectorize(
      baseId.value,
      documentId.value,
      document.value.revision,
      selectedModel.value,
    )
    await load()
    message.success('向量化任务已加入队列')
  } catch (error: unknown) {
    showError(error)
  } finally {
    saving.value = false
  }
}
async function download(): Promise<void> {
  if (!document.value) return
  try {
    const blob = await knowledgeApi.original(baseId.value, documentId.value)
    const url = URL.createObjectURL(blob)
    const link = window.document.createElement('a')
    link.href = url
    link.download = document.value.filename
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error: unknown) {
    showError(error)
  }
}
async function remove(): Promise<void> {
  saving.value = true
  try {
    await knowledgeApi.remove(baseId.value, documentId.value)
    message.success('文档已删除')
    await router.push(`/knowledge/${baseId.value}`)
  } catch (error: unknown) {
    showError(error)
  } finally {
    saving.value = false
  }
}
async function loadSegments(): Promise<void> {
  try {
    const result = await knowledgeApi.segments(baseId.value, documentId.value, segmentPage.value)
    segments.value = result.items
    segmentTotal.value = result.total
  } catch (error: unknown) {
    showError(error)
  }
}
async function loadVersions(): Promise<void> {
  try {
    versions.value = await knowledgeApi.versions(baseId.value, documentId.value)
  } catch (error: unknown) {
    showError(error)
  }
}
async function compare(otherId: string): Promise<void> {
  comparing.value = true
  try {
    comparison.value = await knowledgeApi.compare(baseId.value, documentId.value, otherId)
  } catch (error: unknown) {
    showError(error)
  } finally {
    comparing.value = false
  }
}
async function loadAudit(): Promise<void> {
  try {
    audit.value = await knowledgeApi.audit(baseId.value, documentId.value, auditPage.value)
  } catch (error: unknown) {
    showError(error)
  }
}
async function changeAuditPage(delta: number): Promise<void> {
  auditPage.value += delta
  await loadAudit()
}
async function viewHistory(): Promise<void> {
  if (!historyRevision.value) return
  try {
    historical.value = await knowledgeApi.detail(
      baseId.value,
      documentId.value,
      historyRevision.value,
    )
  } catch (error: unknown) {
    showError(error)
  }
}
function processingMessage(): void {
  if (!document.value) return
  message.info(
    document.value.embedding_status === 'FAILED'
      ? document.value.embedding_message || document.value.status_message
      : document.value.status_message,
  )
}
watch(activeTab, (tab) => {
  if (tab === 'segments') void loadSegments()
  if (tab === 'versions') void loadVersions()
  if (tab === 'audit') void loadAudit()
})
onMounted(async () => {
  await Promise.allSettled([
    load(),
    (async () => {
      try {
        models.value = (await configApi.models())
          .filter((model) => model.enabled && model.model_type === 'embedding')
          .map((model) => ({ label: model.name, value: model.id }))
      } catch (error: unknown) {
        showError(error)
      }
    })(),
  ])
})
onUnmounted(() => {
  disposed = true
  clearTimeout(timer)
})
</script>
<template>
  <section class="kb-page">
    <RouterLink class="kb-back" :to="`/knowledge/${baseId}`">← 返回文档列表</RouterLink
    ><NSpin :show="loading">
      <template v-if="document"
        ><header class="kb-heading">
          <div>
            <span class="kb-eyebrow">SOURCE & STRUCTURE</span>
            <h1>{{ document.metadata.title || document.filename }}</h1>
            <p>
              {{ document.filename }} · {{ document.mode === 'LEGAL' ? '法律法规' : '普通文档' }} ·
              当前修订 r{{ document.revision }}
            </p>
          </div>
          <div class="kb-actions">
            <NButton @click="download">下载原件</NButton
            ><NButton :disabled="saving || loading" @click="load">刷新</NButton>
          </div>
        </header>
        <div class="kb-inline kb-document-tags">
          <NTag
            :type="
              document.status === 'PUBLISHED'
                ? 'success'
                : document.status === 'FAILED'
                  ? 'error'
                  : 'warning'
            "
            >{{ statusLabels[document.status] }}</NTag
          ><NTag>{{ sourceLabels[document.source_kind] }}</NTag
          ><NTag v-if="document.mode === 'LEGAL'">{{ legalLabels[document.legal_status] }}</NTag
          ><NButton text @click="processingMessage">查看处理说明</NButton>
        </div>
        <div class="kb-panel">
          <ProcessingProgress :document="document" />
          <div class="kb-toolbar">
            <NSelect
              v-model:value="selectedModel"
              :options="models"
              clearable
              :disabled="disabled"
              placeholder="选择 Embedding 模型"
              class="kb-model-select"
            /><NButton
              :disabled="disabled || !document.chunk_count || !selectedModel"
              :loading="saving"
              @click="vectorize"
              >{{ document.embedding_status === 'FAILED' ? '重试向量化' : '开始向量化' }}</NButton
            ><RouterLink v-if="!models.length" to="/settings/models" class="kb-link"
              >配置 Embedding 模型</RouterLink
            >
          </div>
        </div>
        <NTabs v-model:value="activeTab" type="line"
          ><NTabPane name="review" tab="结构与审核">
            <p class="kb-note">
              修改只作用于提取信息与原文标注。保存修订会撤销旧版发布，并重新切分；原始文件和历次解析保留。
            </p>
            <template v-if="detail?.result"
              ><div class="kb-review-grid">
                <div class="kb-panel kb-form">
                  <h3>{{ document.mode === 'LEGAL' ? '法律元数据' : '文档信息' }}</h3>
                  <label
                    >名称<NInput
                      v-model:value="metadata.title"
                      :maxlength="300"
                      :disabled="disabled"
                  /></label>
                  <div class="kb-form-grid">
                    <label
                      >法规类别<NSelect
                        v-model:value="metadata.category"
                        :options="
                          Object.entries(categoryLabels).map(([value, label]) => ({ value, label }))
                        "
                        :disabled="disabled"
                    /></label>
                    <label
                      >适用地区<NInput
                        v-model:value="metadata.region"
                        :maxlength="100"
                        placeholder="如：全国、上海市；按原文填写"
                        :disabled="disabled"
                    /></label>
                    <label
                      >公布机关<NInput
                        v-model:value="metadata.authority"
                        :maxlength="300"
                        :disabled="disabled" /></label
                    ><label
                      >文号<NInput
                        v-model:value="metadata.document_number"
                        :maxlength="200"
                        :disabled="disabled" /></label
                    ><label
                      >公布日期<input
                        v-model="metadata.promulgated_on"
                        type="date"
                        :disabled="disabled"
                        @change="metadata.promulgated_on ||= null" /></label
                    ><label
                      >施行日期<input
                        v-model="metadata.effective_on"
                        type="date"
                        :disabled="disabled"
                        @change="metadata.effective_on ||= null"
                    /></label>
                  </div>
                  <label
                    >版本说明<NInput
                      v-model:value="metadata.version_label"
                      :maxlength="200"
                      placeholder="例如：2024 年修订版；不自动推断现行有效"
                      :disabled="disabled" /></label
                  ><NCheckbox v-model:checked="review.version_confirmed" :disabled="disabled"
                    >已对照原件确认法律版本</NCheckbox
                  ><label
                    >法律效力状态<NSelect
                      v-model:value="review.legal_status"
                      :options="legalOptions"
                      :disabled="disabled" /></label
                  ><label
                    >来源分类<NSelect
                      v-model:value="review.source_kind"
                      :options="sourceOptions"
                      :disabled="disabled" /></label
                  ><label
                    >来源地址<NInput
                      v-model:value="review.source_url"
                      :maxlength="2000"
                      :disabled="disabled" /></label
                  ><label
                    >来源说明<NInput
                      v-model:value="review.source_note"
                      type="textarea"
                      :maxlength="2000"
                      :disabled="disabled" /></label
                  ><label
                    >官方核验说明<NInput
                      v-model:value="review.verification_note"
                      type="textarea"
                      :maxlength="2000"
                      placeholder="官方已核验需填写核验说明和官方来源地址"
                      :disabled="disabled"
                  /></label>
                </div>
                <div class="kb-panel">
                  <h3>
                    结构校验 <span class="kb-muted">{{ detail.result.issues.length }} 项</span>
                  </h3>
                  <NEmpty v-if="!detail.result.issues.length" description="当前未检出结构问题" />
                  <div v-for="issue in detail.result.issues" :key="issue.id" class="kb-issue">
                    <NTag size="small" :type="issue.severity === 'ERROR' ? 'error' : 'warning'">{{
                      issue.severity === 'ERROR' ? '需修正' : '需检查'
                    }}</NTag>
                    <p>{{ issue.message }}</p>
                    <small v-if="issue.start !== null"
                      >原文位置 {{ issue.start }}–{{ issue.end
                      }}<template v-if="issue.node_id"> · {{ issue.node_id }}</template></small
                    ><NCheckbox
                      v-if="issue.severity === 'WARNING'"
                      :checked="acknowledged.includes(issue.id)"
                      :disabled="disabled"
                      @update:checked="setAcknowledged(issue.id, $event)"
                      >已核对原件并确认</NCheckbox
                    >
                  </div>
                  <p class="kb-muted">
                    错误不能通过勾选跳过。条文不连续仅作检查提示，确认后可保留原编号。
                  </p>
                </div>
              </div>
              <div v-if="document.mode === 'LEGAL'" class="kb-panel">
                <StructureEditor v-model="nodes" :text="detail.result.text" :disabled="disabled" />
              </div>
              <div class="kb-panel kb-form">
                <label
                  >本次校正 / 审核说明<NInput
                    v-model:value="reason"
                    type="textarea"
                    :maxlength="2000"
                    placeholder="说明修改原因或逐项核验依据，将写入审计记录"
                    :disabled="disabled"
                /></label>
                <div class="kb-inline">
                  <NButton
                    type="primary"
                    :loading="saving"
                    :disabled="disabled || !dirty"
                    @click="save"
                    >保存修订与审核确认</NButton
                  ><span v-if="dirty" class="kb-muted">有尚未保存的修改</span>
                </div>
              </div> </template
            ><NEmpty v-else description="完成文本提取与解析后，可在此审核与校正" class="kb-empty" />
            <div class="kb-footer-actions">
              <NButton
                v-if="document.status !== 'PUBLISHED'"
                type="primary"
                :disabled="disabled || !detail?.result || !document.chunk_count"
                @click="requestOperation('publish')"
                >审核并发布</NButton
              ><NButton v-else :disabled="disabled" @click="requestOperation('withdraw')"
                >撤回发布</NButton
              ><NButton :disabled="disabled" @click="requestOperation('reparse')"
                >重新解析原件</NButton
              ><NPopconfirm @positive-click="remove"
                ><template #trigger
                  ><NButton type="error" quaternary :disabled="saving">删除文档</NButton></template
                >删除后立即移出正式搜索。原件、版本和操作历史保留。</NPopconfirm
              >
            </div> </NTabPane
          ><NTabPane name="source" tab="提取原文"
            ><div class="kb-panel">
              <div class="kb-section-heading">
                <h3>原始提取文本</h3>
                <span class="kb-muted"
                  >{{ textChars.length }} 字符 · {{ detail?.result?.parser_version }}</span
                >
              </div>
              <p class="kb-note">
                原文位置按 Unicode 字符从 0 开始计数，结束位置不包含该字符。此处展示提取文本；PDF 页
                / DOCX 段落对应关系可在下方查看。
              </p>
              <p class="kb-muted">
                当前区间 [{{ (sourcePage - 1) * 5000 }},
                {{ Math.min(sourcePage * 5000, textChars.length) }})
              </p>
              <pre class="kb-source-text">{{ sourceExcerpt }}</pre>
              <NPagination
                v-if="textChars.length > 5000"
                v-model:page="sourcePage"
                :page-size="5000"
                :item-count="textChars.length"
              />
              <details>
                <summary>来源位置与元数据锚点</summary>
                <div class="kb-source-map">
                  <p v-for="(span, index) in visibleSpans" :key="index">
                    {{ span.kind }} {{ span.index }} → [{{ span.start }}, {{ span.end }})
                  </p>
                  <NPagination
                    v-if="sourceSpans.length > 100"
                    v-model:page="sourceMapPage"
                    :page-size="100"
                    :item-count="sourceSpans.length"
                  />
                  <p v-for="anchor in detail?.result?.anchors" :key="anchor.field">
                    {{ anchor.field }} → [{{ anchor.start }}, {{ anchor.end }}) {{ anchor.text }}
                  </p>
                </div>
              </details>
              <p class="kb-hash">原件 SHA-256：{{ document.file_hash }}</p>
              <p class="kb-hash">正文 SHA-256：{{ document.content_hash || '等待提取' }}</p>
            </div></NTabPane
          >
          <NTabPane name="segments" tab="切分片段"
            ><p class="kb-note">
              这些是当前修订的待审片段；仅发布后才进入正式检索。共 {{ segmentTotal }} 个片段。
            </p>
            <article v-for="segment in segments" :key="segment.id" class="kb-search-hit">
              <div class="kb-section-heading">
                <h3>片段 {{ segment.sequence }}</h3>
                <span class="kb-muted"
                  >[{{ segment.start }}, {{ segment.end }}) ·
                  {{ segment.node_id || '通用片段' }}</span
                >
              </div>
              <pre>{{ segment.content }}</pre>
            </article>
            <NEmpty
              v-if="!segments.length"
              description="等待切分结果"
              class="kb-empty" /><NPagination
              v-if="segmentTotal > 10"
              v-model:page="segmentPage"
              :page-size="10"
              :item-count="segmentTotal"
              @update:page="loadSegments"
          /></NTabPane>
          <NTabPane name="versions" tab="法律版本比较"
            ><p class="kb-note">
              综合法律名称、公布机关、文号、原件及正文 Hash
              查找候选。同名资料不会自动合并，历史版本独立保存。
            </p>
            <NEmpty v-if="!versions.length" description="暂无关联版本候选" class="kb-empty" />
            <article v-for="version in versions" :key="version.document.id" class="kb-version-row">
              <div>
                <RouterLink :to="`/knowledge/${baseId}/documents/${version.document.id}`">{{
                  version.document.metadata.title || version.document.filename
                }}</RouterLink>
                <p>
                  {{ version.document.metadata.version_label || '版本待确认' }} ·
                  {{ legalLabels[version.document.legal_status] }}
                </p>
                <small>{{ version.match_reasons.join(' · ') }}</small>
              </div>
              <NButton :loading="comparing" @click="compare(version.document.id)">比较差异</NButton>
            </article>
            <div v-if="comparison" class="kb-panel">
              <h3>与 {{ comparison.right.filename }} 比较</h3>
              <p>
                原件{{ comparison.same_file ? '相同' : '不同' }} · 正文{{
                  comparison.same_content ? '相同' : '不同'
                }}
              </p>
              <p v-for="(values, field) in comparison.metadata_changes" :key="field">
                {{ field }}：{{ values[0] || '未载明' }} → {{ values[1] || '未载明' }}
              </p>
              <p v-if="comparison.truncated" class="kb-note">
                差异较长，当前仅展示部分；请下载原件核对全文。
              </p>
              <pre class="kb-diff">{{ comparison.diff || '当前比较范围未发现正文差异' }}</pre>
            </div></NTabPane
          >
          <NTabPane name="audit" tab="解析与操作记录"
            ><p class="kb-note">
              当前为无登录的单工作空间；操作来源记录为工作空间操作，不推断真实人员身份。
            </p>
            <article v-for="entry in audit" :key="entry.id" class="kb-audit-entry">
              <div class="kb-inline">
                <strong>{{ auditLabels[entry.action] || entry.action }}</strong
                ><NTag v-if="entry.revision !== null" size="small">r{{ entry.revision }}</NTag
                ><span class="kb-muted">{{
                  new Date(entry.created_at).toLocaleString('zh-CN')
                }}</span>
              </div>
              <p>{{ entry.reason }}</p>
              <details>
                <summary>变更记录</summary>
                <pre>{{ JSON.stringify(entry.details, null, 2) }}</pre>
              </details>
            </article>
            <div class="kb-inline">
              <NButton :disabled="auditPage === 1" @click="changeAuditPage(-1)">上一页</NButton
              ><span>{{ auditPage }}</span
              ><NButton :disabled="audit.length < 20" @click="changeAuditPage(1)">下一页</NButton>
            </div>
            <div class="kb-panel kb-form">
              <h3>查看解析历史</h3>
              <div class="kb-toolbar">
                <NInputNumber
                  v-model:value="historyRevision"
                  :min="1"
                  :max="document.revision || 1"
                  placeholder="修订号"
                /><NButton @click="viewHistory">读取历史快照</NButton>
              </div>
              <template v-if="historical?.result"
                ><p>
                  {{ historical.result.metadata.title }} · {{ historical.result.method }} ·
                  {{ historical.result.nodes.length }} 个结构节点
                </p>
                <details>
                  <summary>完整历史解析结果</summary>
                  <pre class="kb-diff">{{ JSON.stringify(historical.result, null, 2) }}</pre>
                </details></template
              >
            </div></NTabPane
          ></NTabs
        > </template
      ><NEmpty v-else-if="!loading" description="暂无可显示的文档" class="kb-empty"
        ><template #extra><NButton @click="load">重新加载</NButton></template></NEmpty
      > </NSpin
    ><NModal
      :show="operation !== null"
      preset="card"
      :title="operation ? actionLabels[operation] : ''"
      class="kb-modal"
      :mask-closable="!saving"
      :closable="!saving"
      @update:show="
        (value) => {
          if (!value) operation = null
        }
      "
      ><div class="kb-form">
        <p class="kb-note">
          {{
            operation === 'publish'
              ? '发布会将当前修订的原文片段加入正式搜索，法律版本与全部校验提示须已确认。'
              : operation === 'reparse'
                ? '将保留原件与历史解析，撤销当前发布，重新提取与切分。人工校正内容留在历史修订中。'
                : '撤回后将立即移除正式搜索片段。'
          }}
        </p>
        <label
          >操作说明<NInput
            v-model:value="operationReason"
            type="textarea"
            :maxlength="2000" /></label
        ><NButton type="primary" :loading="saving" @click="runOperation">确认操作</NButton>
      </div></NModal
    >
  </section>
</template>
