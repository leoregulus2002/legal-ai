<script setup lang="ts">
import { computed } from 'vue'
import { NButton } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'

const props = defineProps<{ status: 'idle' | 'loading' | 'ok' | 'error' }>()
defineEmits<{ refresh: [] }>()
const labels = { idle: '等待检查', loading: '正在检查', ok: '服务正常', error: '服务不可用' }
const label = computed(() => labels[props.status])
</script>

<template>
  <section class="service-status" aria-label="后端服务状态">
    <div class="status-content" role="status" aria-live="polite">
      <span class="status-caption">后端服务状态</span
      ><span class="status-result" :class="status"
        ><span class="status-dot" :class="status" /><span>{{ label }}</span></span
      >
    </div>
    <NButton
      class="refresh-button"
      quaternary
      size="small"
      :loading="status === 'loading'"
      :disabled="status === 'loading'"
      aria-label="刷新后端服务状态"
      @click="$emit('refresh')"
      ><template #icon><AppIcon name="refresh" :size="17" /></template>刷新状态</NButton
    >
  </section>
</template>
