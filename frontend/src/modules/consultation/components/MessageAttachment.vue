<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { NButton, NImagePreview } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { consultationApi } from '../api'
import type { Attachment } from '../types'

const props = defineProps<{ file: Attachment }>()
const showError = useErrorMessage()
const preview = ref('')
const previewOpen = ref(false)
const isImage = computed(() => props.file.mime_type.startsWith('image/'))
let imageRequest: Promise<void> | undefined
let disposed = false

function loadPreview(): Promise<void> {
  if (preview.value || disposed) return Promise.resolve()
  imageRequest ??= consultationApi
    .downloadAttachment(props.file.id)
    .then((blob) => {
      if (!disposed) preview.value = URL.createObjectURL(blob)
    })
    .finally(() => {
      imageRequest = undefined
    })
  return imageRequest
}

onMounted(async () => {
  if (!isImage.value) return
  try {
    await loadPreview()
  } catch (error: unknown) {
    if (!disposed) showError(error)
  }
})

onBeforeUnmount(() => {
  disposed = true
  if (preview.value) URL.revokeObjectURL(preview.value)
})

async function openAttachment(): Promise<void> {
  try {
    if (isImage.value) {
      await loadPreview()
      if (!disposed) previewOpen.value = true
      return
    }
    const blob = await consultationApi.downloadAttachment(props.file.id)
    if (disposed) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = props.file.name
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error: unknown) {
    if (!disposed) showError(error)
  }
}
</script>

<template>
  <NButton
    class="message-file"
    size="small"
    secondary
    :aria-label="`${isImage ? '预览图片' : '下载附件'} ${file.name}`"
    :title="file.name"
    @click="openAttachment"
  >
    <img v-if="preview" :src="preview" :alt="file.name" class="message-file-preview" />
    <AppIcon v-else name="document" :size="20" />
    <span class="message-file-name">{{ file.name }}</span>
  </NButton>
  <NImagePreview v-if="preview" v-model:show="previewOpen" :src="preview" />
</template>
