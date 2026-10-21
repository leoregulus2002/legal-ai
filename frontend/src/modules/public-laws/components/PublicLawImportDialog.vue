<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { NButton, NEmpty, NModal, NSelect, NSpin, useMessage } from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { knowledgeApi } from '../../knowledge/api'
import { configApi } from '../../system-config/api'
import type { VectorizationRequestMode } from '../../system-config/types'
import { publicLawApi } from '../api'
import type { PublicLaw, PublicLawQuery, VectorTask } from '../types'

const props = defineProps<{ laws: PublicLaw[]; query?: PublicLawQuery | null }>()
const emit = defineEmits<{ close: []; started: [task: VectorTask] }>()
const message = useMessage()
const showError = useErrorMessage()
const baseId = ref<string | null>(null)
const modelId = ref<string | null>(null)
const concurrency = ref(1)
const requestMode = ref<VectorizationRequestMode>('concurrent')
const bases = ref<{ label: string; value: string }[]>([])
const models = ref<{ label: string; value: string }[]>([])
const loading = ref(false)
const optionsLoaded = ref(false)
const basesLoading = ref(false)
const submitting = ref(false)
let alive = true
let optionsSequence = 0
let basesSequence = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined

async function loadBases(query = ''): Promise<void> {
  const request = ++basesSequence
  basesLoading.value = true
  try {
    const data = await knowledgeApi.bases(query, 1, 100)
    if (!alive || request !== basesSequence) return
    bases.value = data.items.map((base) => ({ label: base.name, value: base.id }))
  } catch (error: unknown) {
    if (alive && request === basesSequence) showError(error)
  } finally {
    if (alive && request === basesSequence) basesLoading.value = false
  }
}

function searchBases(query: string): void {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    void loadBases(query)
  }, 300)
}

async function loadOptions(): Promise<void> {
  const request = ++optionsSequence
  loading.value = true
  try {
    const [basePage, configurations, vectorization] = await Promise.all([
      knowledgeApi.bases('', 1, 100),
      configApi.models(),
      configApi.vectorization(),
    ])
    if (!alive || request !== optionsSequence) return
    bases.value = basePage.items.map((base) => ({ label: base.name, value: base.id }))
    concurrency.value = vectorization.concurrency
    requestMode.value = vectorization.request_mode
    models.value = configurations
      .filter((model) => model.enabled && model.model_type === 'embedding')
      .map((model) => ({ label: model.name, value: model.id }))
    if (bases.value.length === 1) baseId.value = bases.value[0]!.value
    if (models.value.length === 1) modelId.value = models.value[0]!.value
    optionsLoaded.value = true
  } catch (error: unknown) {
    if (alive && request === optionsSequence) showError(error)
  } finally {
    if (alive && request === optionsSequence) loading.value = false
  }
}

async function submit(): Promise<void> {
  if (submitting.value) return
  if (!baseId.value || !modelId.value) {
    message.warning('请选择知识库和向量模型')
    return
  }
  const selectedBase = baseId.value
  const selectedModel = modelId.value
  submitting.value = true
  try {
    const task = await publicLawApi.startTask(
      selectedBase,
      selectedModel,
      props.query ? { query: props.query } : { laws: props.laws },
    )
    if (!alive) return
    message.success(
      task.request_mode === 'serial'
        ? '任务已开始，采用线性请求模式逐条处理'
        : `任务已开始，采用并发请求模式，解析与向量化并发 ${task.concurrency}`,
    )
    emit('started', task)
    emit('close')
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) submitting.value = false
  }
}

watch(
  () => props.laws.length > 0 || Boolean(props.query),
  (show) => {
    optionsSequence++
    basesSequence++
    clearTimeout(searchTimer)
    basesLoading.value = false
    loading.value = false
    if (!show) {
      return
    }
    baseId.value = null
    modelId.value = null
    bases.value = []
    models.value = []
    optionsLoaded.value = false
    void loadOptions()
  },
)
onUnmounted(() => {
  alive = false
  optionsSequence++
  basesSequence++
  clearTimeout(searchTimer)
})
</script>

<template>
  <NModal
    :show="laws.length > 0 || Boolean(query)"
    preset="card"
    title="一键向量化"
    class="public-law-import-dialog"
    :mask-closable="false"
    :closable="!submitting"
    :close-on-esc="!submitting"
    @update:show="
      (show) => {
        if (!show && !submitting) emit('close')
      }
    "
  >
    <NSpin :show="loading">
      <p class="public-law-import-note">
        {{
          query ? '处理当前检索条件下的全部法规，不限当前页。' : `处理所选 ${laws.length} 条法规。`
        }}
        请求模式采用系统统一配置，已向量化法规自动跳过。支持随时停止，关闭页面后任务继续运行。
      </p>
      <div class="public-law-import-fields">
        <label
          >目标知识库<NSelect
            v-model:value="baseId"
            :options="bases"
            :loading="basesLoading"
            :disabled="submitting"
            remote
            filterable
            clearable
            placeholder="搜索并选择知识库"
            aria-label="目标知识库"
            @search="searchBases"
        /></label>
        <label
          >向量模型<NSelect
            v-model:value="modelId"
            :options="models"
            :disabled="submitting"
            filterable
            placeholder="选择已启用的向量模型"
            aria-label="向量模型"
        /></label>
      </div>
      <p class="public-law-import-note">
        <template v-if="optionsLoaded">
          <template v-if="requestMode === 'serial'">
            当前配置：线性请求，逐条完成下载、解析与向量化。
          </template>
          <template v-else>
            当前配置：并发请求，下载并发 1，解析与向量化并发 {{ concurrency }}。
          </template>
        </template>
        <RouterLink to="/settings/vectorization" @click="emit('close')">调整请求模式</RouterLink>
      </p>
      <p class="public-law-import-note">
        <RouterLink to="/knowledge" @click="emit('close')">前往管理或新建知识库</RouterLink>
      </p>
      <NButton v-if="!loading && !optionsLoaded" @click="loadOptions">重新加载知识库与模型</NButton>
      <NEmpty v-if="optionsLoaded && !models.length" description="暂无已启用的向量模型"
        ><template #extra
          ><RouterLink to="/settings/models" @click="emit('close')"
            >前往配置向量模型</RouterLink
          ></template
        ></NEmpty
      >
      <ul v-if="!query" class="public-law-import-items">
        <li v-for="law in laws" :key="law.id">
          <span>{{ law.title }}</span>
        </li>
      </ul>
      <div class="public-law-import-actions">
        <NButton :disabled="submitting" @click="emit('close')">关闭</NButton
        ><NButton
          type="primary"
          :loading="submitting"
          :disabled="loading || !baseId || !modelId"
          @click="submit"
          >开始向量化</NButton
        >
      </div>
    </NSpin>
  </NModal>
</template>
