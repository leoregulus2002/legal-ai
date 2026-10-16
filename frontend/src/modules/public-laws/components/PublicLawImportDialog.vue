<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { NButton, NEmpty, NModal, NSelect, NSpin, useMessage } from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { knowledgeApi } from '../../knowledge/api'
import { configApi } from '../../system-config/api'
import { publicLawApi } from '../api'
import type { PublicLaw, PublicLawImportResult } from '../types'
import { vectorizationLabels } from '../types'

const props = defineProps<{ laws: PublicLaw[] }>()
const emit = defineEmits<{ close: []; imported: [] }>()
const message = useMessage()
const showError = useErrorMessage()
const baseId = ref<string | null>(null)
const modelId = ref<string | null>(null)
const bases = ref<{ label: string; value: string }[]>([])
const models = ref<{ label: string; value: string }[]>([])
const loading = ref(false)
const optionsLoaded = ref(false)
const basesLoading = ref(false)
const submitting = ref(false)
const completed = ref<Record<string, PublicLawImportResult>>({})
const currentTitle = ref('')
const remaining = computed(() => props.laws.filter((law) => !completed.value[law.id]))
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
    const [basePage, configurations] = await Promise.all([
      knowledgeApi.bases('', 1, 100),
      configApi.models(),
    ])
    if (!alive || request !== optionsSequence) return
    bases.value = basePage.items.map((base) => ({ label: base.name, value: base.id }))
    models.value = configurations
      .filter((model) => model.enabled && model.model_type === 'embedding')
      .map((model) => ({ label: model.name, value: model.id }))
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
  const pending = [...remaining.value]
  submitting.value = true
  let accepted = 0
  let existing = 0
  try {
    for (const law of pending) {
      if (!alive) break
      currentTitle.value = law.title
      try {
        const data = await publicLawApi.importLaw(law, selectedBase, selectedModel)
        if (!alive) break
        completed.value[law.id] = data
        if (data.action === 'EXISTING') existing++
        else accepted++
      } catch (error: unknown) {
        if (alive) showError(error)
      }
    }
  } finally {
    if (alive) {
      submitting.value = false
      currentTitle.value = ''
      if (accepted) message.success(`已提交 ${accepted} 条法规，后台将自动解析、切分并向量化`)
      if (existing) message.info(`${existing} 条法规已在此知识库中，未重复导入`)
      if (accepted || existing) emit('imported')
    }
  }
}

watch(
  () => props.laws,
  (laws) => {
    optionsSequence++
    basesSequence++
    clearTimeout(searchTimer)
    basesLoading.value = false
    loading.value = false
    if (!laws.length) {
      return
    }
    completed.value = {}
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
    :show="laws.length > 0"
    preset="card"
    title="导入知识库并向量化"
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
        导入官方原件后，后台会自动解析、切分并调用所选向量模型。完成后仍需在知识库中审核发布。
      </p>
      <div class="public-law-import-fields">
        <label
          >目标知识库<NSelect
            v-model:value="baseId"
            :options="bases"
            :loading="basesLoading"
            :disabled="submitting || Object.keys(completed).length > 0"
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
            :disabled="submitting || Object.keys(completed).length > 0"
            filterable
            placeholder="选择已启用的向量模型"
            aria-label="向量模型"
        /></label>
      </div>
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
      <p class="public-law-import-progress" aria-live="polite">
        已处理 {{ Object.keys(completed).length }} / {{ laws.length }} 条<span v-if="currentTitle">
          · 正在导入：{{ currentTitle }}</span
        >
      </p>
      <ul class="public-law-import-items">
        <li v-for="law in laws" :key="law.id">
          <span>{{ law.title }}</span
          ><RouterLink
            v-if="completed[law.id]"
            :to="`/knowledge/${completed[law.id]!.state.knowledge_base_id}/documents/${completed[law.id]!.state.document_id}`"
            >{{ vectorizationLabels[completed[law.id]!.state.status] }} · 查看文档</RouterLink
          >
        </li>
      </ul>
      <div class="public-law-import-actions">
        <NButton :disabled="submitting" @click="emit('close')">{{
          remaining.length ? '关闭' : '完成'
        }}</NButton
        ><NButton
          v-if="remaining.length"
          type="primary"
          :loading="submitting"
          :disabled="loading || !baseId || !modelId"
          @click="submit"
          >导入并向量化（{{ remaining.length }}）</NButton
        >
      </div>
    </NSpin>
  </NModal>
</template>
