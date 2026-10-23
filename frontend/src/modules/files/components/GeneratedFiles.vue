<script setup lang="ts">
import { ref } from 'vue'
import { NButton } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { apiClient } from '../../../api/client'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import type { GeneratedFile } from '../types'

defineProps<{ files: GeneratedFile[] }>()
const downloading = ref<string[]>([])
const showError = useErrorMessage()

function sizeLabel(size: number): string {
  return size < 1024
    ? `${size} B`
    : size < 1024 * 1024
      ? `${Math.ceil(size / 1024)} KB`
      : `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function download(file: GeneratedFile): Promise<void> {
  if (downloading.value.includes(file.id)) return
  downloading.value.push(file.id)
  try {
    const response = await apiClient.get<Blob>(`/files/${encodeURIComponent(file.id)}`, {
      responseType: 'blob',
      timeout: 60000,
    })
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = file.name
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error: unknown) {
    showError(error)
  } finally {
    downloading.value = downloading.value.filter((id) => id !== file.id)
  }
}
</script>

<template>
  <div v-if="files.length" class="generated-files" aria-label="生成的文件">
    <div v-for="file in files" :key="file.id" class="generated-file">
      <AppIcon name="document" :size="23" />
      <div class="generated-file-info">
        <strong :title="file.name">{{ file.name }}</strong
        ><span>{{ sizeLabel(file.size) }}</span>
      </div>
      <NButton
        size="small"
        secondary
        :loading="downloading.includes(file.id)"
        :aria-label="`下载 ${file.name}`"
        @click="download(file)"
        >下载</NButton
      >
    </div>
  </div>
</template>

<style scoped>
.generated-files {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}
.generated-file {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border-color, #e1e7eb);
  border-radius: 12px;
  background: var(--card-color, #f7f9fb);
  max-width: 520px;
}
.generated-file > svg {
  flex-shrink: 0;
  color: #40647b;
}
.generated-file-info {
  display: grid;
  gap: 3px;
  min-width: 0;
  flex: 1;
}
.generated-file-info strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 500;
}
.generated-file-info span {
  font-size: 12px;
  color: #7a8793;
}
</style>
