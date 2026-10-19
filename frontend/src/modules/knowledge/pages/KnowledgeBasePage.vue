<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  NButton,
  NEmpty,
  NInput,
  NModal,
  NPagination,
  NPopconfirm,
  NProgress,
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
import type { KnowledgeBase, KnowledgeDocument, SearchHit, SearchPage, ImportMode } from '../types'
import { isProcessing, legalLabels, sourceLabels, statusLabels } from '../types'
import '../styles.css'
const route = useRoute()
const baseId = computed(() => String(route.params.baseId))
const base = ref<KnowledgeBase>()
const documents = ref<KnowledgeDocument[]>([])
const loading = ref(false)
const query = ref('')
const status = ref('')
const page = ref(1)
const total = ref(0)
const uploadOpen = ref(false)
const uploading = ref(false)
const uploadPercent = ref(0)
const files = ref<File[]>([])
const fileInput = ref<HTMLInputElement>()
const form = reactive({
  mode: 'LEGAL' as ImportMode,
  source_url: '',
  source_note: '',
  model_id: null as string | null,
})
const models = ref<{ label: string; value: string }[]>([])
const searchQuery = ref('')
const searchModel = ref<string | null>(null)
const hits = ref<SearchHit[]>([])
const searchTotal = ref(0)
const searchPage = ref(1)
const searching = ref(false)
const searched = ref(false)
const searchMethod = ref<SearchPage['retrieval_method']>()
const activeTab = ref('documents')
const deleting = ref<string | null>(null)
const showError = useErrorMessage()
const message = useMessage()
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let requestId = 0
let searchRequestId = 0
const statusOptions = Object.entries(statusLabels).map(([value, label]) => ({ value, label }))
async function load(showSpinner = true): Promise<void> {
  clearTimeout(timer)
  const request = ++requestId
  if (showSpinner) loading.value = true
  try {
    const result = await knowledgeApi.documents(baseId.value, query.value, page.value, status.value)
    if (disposed || request !== requestId) return
    documents.value = result.items
    total.value = result.total
    // 任务在当前筛选页不可见时也定期刷新，避免完成后无法进入筛选结果。
    timer = setTimeout(
      () => {
        void load(false)
      },
      documents.value.some(isProcessing) ? 2000 : 8000,
    )
  } catch (error: unknown) {
    if (!disposed && request === requestId) showError(error)
  } finally {
    if (request === requestId) loading.value = false
  }
}
async function submitQuery(): Promise<void> {
  page.value = 1
  await load()
}
function chooseFiles(event: Event): void {
  if (event.target instanceof HTMLInputElement) files.value = Array.from(event.target.files ?? [])
}
async function upload(): Promise<void> {
  if (!files.value.length) {
    message.warning('请选择需要导入的文件')
    return
  }
  if (!form.model_id) {
    message.warning('请选择 Embedding 模型，处理成功后将自动发布')
    return
  }
  if (files.value.some((file) => file.size > 25 * 1024 * 1024)) {
    message.warning('单个文件不能超过 25 MB')
    return
  }
  uploading.value = true
  try {
    const pending = [...files.value]
    for (const file of pending) {
      const data = new FormData()
      data.set('file', file)
      data.set('mode', form.mode)
      data.set('source_url', form.source_url)
      data.set('source_note', form.source_note)
      if (form.model_id) data.set('embedding_model_id', form.model_id)
      uploadPercent.value = 0
      await knowledgeApi.upload(baseId.value, data, (percent) => {
        uploadPercent.value = percent
      })
      files.value = files.value.filter((item) => item !== file)
    }
    uploadOpen.value = false
    if (fileInput.value) fileInput.value.value = ''
    page.value = 1
    status.value = ''
    query.value = ''
    message.success('文件已保存，后台处理成功后将自动发布')
  } catch (error: unknown) {
    showError(error)
  } finally {
    uploading.value = false
    await load()
  }
}
async function remove(document: KnowledgeDocument): Promise<void> {
  deleting.value = document.id
  try {
    await knowledgeApi.remove(baseId.value, document.id)
    if (documents.value.length === 1 && page.value > 1) page.value--
    await load()
    message.success('文档已删除，正式索引已移除')
  } catch (error: unknown) {
    showError(error)
  } finally {
    deleting.value = null
  }
}
async function search(reset = false): Promise<void> {
  if (!searchQuery.value.trim()) {
    message.warning('请输入搜索内容')
    return
  }
  if (reset) searchPage.value = 1
  const request = ++searchRequestId
  hits.value = []
  searched.value = false
  searchMethod.value = undefined
  searching.value = true
  try {
    const result = await knowledgeApi.search(
      searchQuery.value.trim(),
      baseId.value,
      searchPage.value,
      searchModel.value ?? undefined,
    )
    if (disposed || request !== searchRequestId) return
    hits.value = result.items
    searchTotal.value = result.total
    searchMethod.value = result.retrieval_method
    searched.value = true
  } catch (error: unknown) {
    if (!disposed && request === searchRequestId) showError(error)
  } finally {
    if (!disposed && request === searchRequestId) searching.value = false
  }
}
function matchLabel(hit: SearchHit): string {
  if (hit.lexical_rank != null && hit.vector_rank != null) return '关键词与语义均匹配'
  return hit.lexical_rank != null ? '关键词匹配' : '语义匹配'
}
function matchDetails(hit: SearchHit): string {
  return [
    hit.bm25_score != null ? `BM25 ${hit.bm25_score.toFixed(3)}` : '',
    hit.cosine_score != null ? `余弦相似度 ${hit.cosine_score.toFixed(3)}` : '',
    hit.keyword_coverage != null ? `词项覆盖率 ${Math.round(hit.keyword_coverage * 100)}%` : '',
    `RRF 融合分数 ${hit.fusion_score.toFixed(5)}`,
  ]
    .filter(Boolean)
    .join('；')
}
onMounted(async () => {
  await Promise.allSettled([
    load(),
    (async () => {
      try {
        base.value = await knowledgeApi.base(baseId.value)
      } catch (error: unknown) {
        showError(error)
      }
    })(),
    (async () => {
      try {
        models.value = (await configApi.models())
          .filter((model) => model.model_type === 'embedding' && model.enabled)
          .map((model) => ({ label: model.name, value: model.id }))
        form.model_id ??= models.value[0]?.value ?? null
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
    <RouterLink class="kb-back" to="/knowledge">← 全部知识库</RouterLink>
    <header class="kb-heading">
      <div>
        <span class="kb-eyebrow">DOCUMENT COLLECTION</span>
        <h1>{{ base?.name || '知识库' }}</h1>
        <p>{{ base?.description || '从原始资料到可核验的法律知识。' }}</p>
      </div>
      <NButton type="primary" @click="uploadOpen = true">上传文档</NButton>
    </header>
    <NTabs v-model:value="activeTab" type="line" animated
      ><NTabPane name="documents" tab="文档管理">
        <form class="kb-toolbar" @submit.prevent="submitQuery">
          <NInput
            v-model:value="query"
            placeholder="搜索文件名或法律名称"
            :maxlength="200"
            clearable
          /><NSelect
            v-model:value="status"
            :options="[{ label: '全部状态', value: '' }, ...statusOptions]"
            class="kb-status-filter"
          /><NButton attr-type="submit" :loading="loading">查询</NButton
          ><span class="kb-muted">共 {{ total }} 份文档</span>
        </form>
        <NSpin :show="loading"
          ><NEmpty
            v-if="!documents.length && !loading"
            description="暂无文档，支持多种格式直接导入"
            class="kb-empty"
          />
          <div class="kb-doc-list">
            <article v-for="document in documents" :key="document.id" class="kb-doc-row">
              <div class="kb-doc-info">
                <div class="kb-inline">
                  <NTag
                    size="small"
                    :type="
                      document.status === 'PUBLISHED'
                        ? 'success'
                        : document.status === 'FAILED'
                          ? 'error'
                          : 'default'
                    "
                    >{{ statusLabels[document.status] }}</NTag
                  ><span class="kb-muted"
                    >{{ document.mode === 'LEGAL' ? '法律法规' : '普通文档' }} ·
                    {{ (document.size / 1024).toFixed(1) }} KB · r{{ document.revision }}</span
                  >
                </div>
                <RouterLink :to="`/knowledge/${baseId}/documents/${document.id}`"
                  ><h2>{{ document.metadata.title || document.filename }}</h2></RouterLink
                >
                <p class="kb-muted">
                  {{ document.filename }} · {{ sourceLabels[document.source_kind]
                  }}<template v-if="document.mode === 'LEGAL'">
                    · {{ legalLabels[document.legal_status] }}</template
                  >
                </p>
                <p v-if="document.duplicate_of" class="kb-muted">
                  已发现原件 Hash 相同的文件；此文档独立保留。
                </p>
              </div>
              <ProcessingProgress :document="document" compact />
              <div class="kb-actions">
                <RouterLink :to="`/knowledge/${baseId}/documents/${document.id}`" class="kb-link"
                  >查看与管理</RouterLink
                ><NPopconfirm @positive-click="remove(document)"
                  ><template #trigger
                    ><NButton text type="error" size="small" :loading="deleting === document.id"
                      >删除</NButton
                    ></template
                  >删除文档并移出正式搜索？原件及解析历史保留。</NPopconfirm
                >
              </div>
            </article>
          </div> </NSpin
        ><NPagination
          v-if="total > 12"
          v-model:page="page"
          :page-size="12"
          :item-count="total"
          @update:page="load()"
        /> </NTabPane
      ><NTabPane name="search" tab="正式内容搜索">
        <p class="kb-note">
          搜索范围仅含已发布文档。发布不代表法律现行有效，历史法律版本保留独立效力标注。
        </p>
        <form class="kb-toolbar" @submit.prevent="search(true)">
          <NInput
            v-model:value="searchQuery"
            placeholder="输入问题或法律术语"
            :maxlength="500"
          /><NSelect
            v-model:value="searchModel"
            :options="models"
            clearable
            placeholder="自动选择可用向量模型"
            class="kb-model-select"
          /><NButton type="primary" attr-type="submit" :loading="searching">搜索</NButton>
        </form>
        <NSpin :show="searching"
          ><p v-if="searched" class="kb-muted">
            {{
              searchMethod === 'hybrid' ? '关键词与语义混合检索' : '关键词检索（暂无可用向量索引）'
            }}
            · 本次 {{ searchTotal }} 个候选片段
          </p>
          <NEmpty
            v-if="searched && !hits.length"
            description="暂无匹配的已发布内容"
            class="kb-empty"
          />
          <article
            v-for="hit in hits"
            :key="`${hit.document_id}:${hit.start}`"
            class="kb-search-hit"
          >
            <RouterLink :to="`/knowledge/${hit.knowledge_base_id}/documents/${hit.document_id}`"
              ><h3>{{ hit.title }}</h3></RouterLink
            >
            <p class="kb-muted">
              {{ sourceLabels[hit.source_kind] }} · {{ legalLabels[hit.legal_status] }} · r{{
                hit.revision
              }}
              · 原文位置 {{ hit.start }}–{{ hit.end }} ·
              <span :title="matchDetails(hit)">{{ matchLabel(hit) }}</span>
            </p>
            <pre>{{ hit.content }}</pre>
          </article></NSpin
        ><NPagination
          v-if="searchTotal > 10"
          v-model:page="searchPage"
          :page-size="10"
          :item-count="searchTotal"
          @update:page="search()"
        /> </NTabPane
    ></NTabs>
    <NModal
      v-model:show="uploadOpen"
      preset="card"
      title="导入文档"
      class="kb-modal"
      :mask-closable="!uploading"
      :closable="!uploading"
      ><div class="kb-form">
        <p class="kb-note">
          无需固定模板。支持 PDF、DOCX、TXT、Markdown、HTML；单文件最多 25 MB。扫描 PDF 的 OCR
          暂未开放。
        </p>
        <label
          >导入方式<NSelect
            v-model:value="form.mode"
            :options="[
              { label: '法律法规 LEGAL · 识别法律层级并校验', value: 'LEGAL' },
              { label: '普通文档 GENERAL · 通用切分', value: 'GENERAL' },
            ]"
            :disabled="uploading" /></label
        ><label
          >选择文件<input
            ref="fileInput"
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md,.markdown,.html,.htm"
            :disabled="uploading"
            @change="chooseFiles"
        /></label>
        <ul v-if="files.length" class="kb-file-list">
          <li v-for="(file, index) in files" :key="index">
            {{ file.name }} · {{ (file.size / 1024).toFixed(1) }} KB
          </li>
        </ul>
        <label
          >向量化模型<NSelect
            v-model:value="form.model_id"
            :options="models"
            clearable
            placeholder="请选择向量化模型"
            :disabled="uploading"
        /></label>
        <p v-if="!models.length" class="kb-muted">请先在“模型配置”添加并启用 Embedding 模型。</p>
        <label
          >来源地址<NInput
            v-model:value="form.source_url"
            :maxlength="2000"
            :disabled="uploading"
            placeholder="可选，原始发布页面" /></label
        ><label
          >来源说明<NInput
            v-model:value="form.source_note"
            type="textarea"
            :maxlength="2000"
            :disabled="uploading"
        /></label>
        <p class="kb-note">
          上传后依次解析、结构化、数据校验、向量化，成功后自动发布；任一步失败均不发布，可查看原因并重试。
        </p>
        <p class="kb-muted">上传资料默认标记“用户上传”，需核验后才能更改来源分类。</p>
        <NProgress
          v-if="uploading"
          type="line"
          :percentage="uploadPercent"
          indicator-placement="inside"
        /><NButton type="primary" :loading="uploading" @click="upload">保存并开始处理</NButton>
      </div></NModal
    >
  </section>
</template>
