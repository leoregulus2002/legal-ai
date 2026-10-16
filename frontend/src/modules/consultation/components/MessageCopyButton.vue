<script setup lang="ts">
import { ref } from 'vue'
import { NButton, useMessage } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'

const props = defineProps<{ text: string; label: string }>()
const message = useMessage()
const copying = ref(false)

async function copy(): Promise<void> {
  if (!props.text.trim() || copying.value) return
  if (!navigator.clipboard?.writeText) {
    message.warning('当前浏览器不支持一键复制，请选中文字后手动复制')
    return
  }
  copying.value = true
  try {
    await navigator.clipboard.writeText(props.text)
    message.success('已复制')
  } catch {
    message.error('复制失败，请选中文字后手动复制')
  } finally {
    copying.value = false
  }
}
</script>

<template>
  <NButton
    class="message-copy"
    quaternary
    circle
    size="small"
    :disabled="!text.trim()"
    :loading="copying"
    :title="label"
    :aria-label="label"
    @click="copy"
  >
    <template #icon><AppIcon name="copy" :size="16" /></template>
  </NButton>
</template>

<style scoped>
.message-copy {
  flex-shrink: 0;
  color: var(--muted);
}
</style>
