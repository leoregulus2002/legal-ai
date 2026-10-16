<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { NButton, NEmpty, NModal, NSpin } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { publicLawApi } from '../api'
import type { PublicLaw, PublicLawDetail, PublicLawFormat } from '../types'
import { statusOptions } from '../types'
import { usePublicLawDownload } from '../usePublicLawDownload'

const props = defineProps<{ law: PublicLaw | null }>()
const emit = defineEmits<{ close: [] }>()
const showError = useErrorMessage()
const { downloadingId, download } = usePublicLawDownload()
const detail = ref<PublicLawDetail>()
const previewUrl = ref<string>()
const format = ref<PublicLawFormat>('docx')
const detailLoading = ref(false)
const previewLoading = ref(false)
const current = computed(() => detail.value ?? props.law)
const status = computed(
  () => statusOptions.find((option) => option.value === current.value?.status)?.label ?? '未标注',
)
const formatLabels = { docx: '电子文本', pdf: '公报原版' }
let detailController: AbortController | undefined
let previewController: AbortController | undefined
let detailSequence = 0
let previewSequence = 0

async function loadPreview(selectedFormat: PublicLawFormat): Promise<void> {
  const law = props.law
  if (!law) return
  const request = ++previewSequence
  previewController?.abort()
  previewController = new AbortController()
  format.value = selectedFormat
  previewUrl.value = undefined
  previewLoading.value = true
  try {
    const data = await publicLawApi.preview(law, selectedFormat, previewController.signal)
    if (request === previewSequence) previewUrl.value = data.url
  } catch (error: unknown) {
    if (request === previewSequence) showError(error)
  } finally {
    if (request === previewSequence) previewLoading.value = false
  }
}

async function loadDetail(): Promise<void> {
  const request = ++detailSequence
  previewSequence++
  detailController?.abort()
  previewController?.abort()
  detail.value = undefined
  previewUrl.value = undefined
  previewLoading.value = false
  detailLoading.value = false
  const law = props.law
  if (!law) return
  detailController = new AbortController()
  detailLoading.value = true
  try {
    const data = await publicLawApi.detail(law, detailController.signal)
    if (request !== detailSequence) return
    detail.value = data
    const initialFormat = data.preview_formats[0]
    if (initialFormat) void loadPreview(initialFormat)
  } catch (error: unknown) {
    if (request === detailSequence) showError(error)
  } finally {
    if (request === detailSequence) detailLoading.value = false
  }
}

watch(
  () => props.law?.id,
  () => {
    void loadDetail()
  },
  { immediate: true },
)
onUnmounted(() => {
  detailSequence++
  previewSequence++
  detailController?.abort()
  previewController?.abort()
})
</script>

<template>
  <NModal
    :show="Boolean(law)"
    preset="card"
    class="public-law-preview"
    :bordered="false"
    :mask-closable="false"
    aria-label="法律法规原文预览"
    @update:show="
      (show) => {
        if (!show) emit('close')
      }
    "
  >
    <template #header><span class="public-law-preview-label">公开法律库 · 原文预览</span></template>
    <div v-if="current" class="public-law-preview-content">
      <header class="public-law-preview-header">
        <h2>{{ current.title }}</h2>
        <div class="public-law-preview-meta">
          <span
            class="public-law-status"
            :class="`public-law-status--${current.status ?? 'unknown'}`"
            >{{ status }}</span
          ><span>{{ current.category || '未标注分类' }}</span
          ><span>{{ current.authority || '未标注制定机关' }}</span
          ><span>公布日期：{{ current.published_on || '未标注' }}</span
          ><span>施行日期：{{ current.effective_on || '未标注' }}</span>
        </div>
      </header>
      <div class="public-law-preview-toolbar">
        <div class="public-law-preview-tabs" role="group" aria-label="预览版本">
          <NButton
            v-for="kind in detail?.preview_formats ?? []"
            :key="kind"
            size="small"
            :type="format === kind ? 'primary' : 'default'"
            :secondary="format === kind"
            :aria-pressed="format === kind"
            @click="loadPreview(kind)"
            >{{ formatLabels[kind] }}</NButton
          >
        </div>
        <div class="public-law-preview-actions">
          <NButton
            size="small"
            :disabled="detailLoading || previewLoading"
            @click="detail?.preview_formats.length ? loadPreview(format) : loadDetail()"
            ><template #icon><AppIcon name="refresh" :size="14" /></template>刷新预览</NButton
          ><NButton
            type="primary"
            size="small"
            :loading="Boolean(downloadingId)"
            @click="download(current, detail?.preview_formats.length ? format : 'docx')"
            >下载{{
              detail?.preview_formats.length ? (format === 'pdf' ? ' PDF' : ' Word') : '文件'
            }}</NButton
          >
        </div>
      </div>
      <NSpin :show="detailLoading || previewLoading" class="public-law-preview-viewer">
        <iframe
          v-if="previewUrl"
          :src="previewUrl"
          :title="`${current.title}原文预览`"
          referrerpolicy="no-referrer"
          sandbox="allow-scripts allow-same-origin allow-downloads allow-modals"
        />
        <NEmpty
          v-else-if="detail && !detail.preview_formats.length"
          description="该法规暂无可预览的文件"
        />
      </NSpin>
    </div>
  </NModal>
</template>
